"""Heuristic engine: quest-aware fallback (mirrors 03-SKILLS.md)."""
from .common import _print_debrief

# Client-side mirror of the quest chain (seed.py): item, hunting ground,
# giver NPC/location, and level gate. Lets the heuristic route without
# needing a server round-trip per decision.
QUEST_META = {
    "q_ratcatcher": {"item_id": "itm_rat_pelt", "hunt": "oakhollow_forest",
                     "giver_npc": "npc_blacksmith", "giver_loc": "riverside_village", "min_level": 1},
    "q_wolfpack": {"item_id": "itm_wolf_pelt", "hunt": "oakhollow_forest",
                   "giver_npc": "npc_scout", "giver_loc": "oakhollow_forest", "min_level": 2},
    "q_bandit_toll": {"item_id": "itm_bandit_dagger", "hunt": "capital_city",
                      "giver_npc": "npc_merchant", "giver_loc": "capital_city", "min_level": 2},
    "q_trollbane": {"item_id": "itm_troll_hide", "hunt": "deep_cave",
                    "giver_npc": "npc_captain", "giver_loc": "capital_city", "min_level": 3},
    "q_marshlight": {"item_id": "itm_wraith_essence", "hunt": "sunken_marsh",
                     "giver_npc": "npc_hermit", "giver_loc": "sunken_marsh", "min_level": 3},
    "q_drakescale": {"item_id": "itm_drake_scale", "hunt": "ember_ridge",
                     "giver_npc": "npc_warden", "giver_loc": "ember_ridge", "min_level": 5},
}

# Fallback grind spots by level when no quest points elsewhere.
GRIND_BY_LEVEL = {1: "oakhollow_forest", 2: "oakhollow_forest",
                  3: "deep_cave", 4: "sunken_marsh", 5: "ember_ridge"}


def _quest_complete(q):
    """True when an active_quest progress string reads have>=need."""
    try:
        prog = q.get("progress", "") if isinstance(q, dict) else ""
        have_s, rest = prog.split("/", 1)
        need_s = rest.split(None, 1)[0]
        return int(have_s) >= int(need_s)
    except (ValueError, IndexError, KeyError, AttributeError):
        return False


def _recent_talk_npcs(recent):
    """NPC ids talked to in the last few turns. Handles str or dict entries."""
    out = []
    for r in (recent or [])[-6:]:
        if isinstance(r, dict):
            if r.get("action") == "talk_to_npc" and isinstance(r.get("params"), dict):
                nid = r["params"].get("npc_id")
                if nid:
                    out.append(nid)
        elif isinstance(r, (list, tuple)) and len(r) == 2:
            if r[0] == "talk_to_npc" and isinstance(r[1], dict) and r[1].get("npc_id"):
                out.append(r[1]["npc_id"])
    return out


def _move_toward(target, world, zones=None):
    """One step toward target location via exits (BFS over zones when known)."""
    exits = [e["to"] for e in world.get("exits", [])]
    if not exits:
        return None
    if target in exits:
        return ("move", {"to": target})
    if zones:
        adj = {}
        for z in zones:
            zid = z.get("id")
            adj[zid] = [e["to"] for e in z.get("exits", [])]
        cur = world.get("location_id") or ""
        # BFS from current to target; fall back to current-location lookup
        if not cur:
            # caller passes location via world; here-block lacks it, use me loc
            cur = _move_toward._cur or ""
        if cur in adj:
            from collections import deque
            prev = {cur: None}
            dq = deque([cur])
            while dq:
                node = dq.popleft()
                if node == target:
                    break
                for nb in adj.get(node, []):
                    if nb not in prev:
                        prev[nb] = node
                        dq.append(nb)
            if target in prev:
                step = target
                if step == cur:
                    return None  # already here; caller falls through
                while prev[step] != cur:
                    step = prev[step]
                if step in exits:
                    return ("move", {"to": step})
    return ("move", {"to": exits[0]})


_move_toward._cur = ""


def decide(status, here, schema, offered=None, accepted=None, recent=None,
           completed=None, zones=None):
    """Quest-aware fallback (mirrors 03-SKILLS.md): survive, take quests, hunt, move on."""
    offered = offered or []
    accepted = accepted or set()
    me = status["data"]
    world = here["data"]
    _move_toward._cur = me.get("location", "")
    hp, max_hp = me["hp"], me["max_hp"]
    if hp <= 0 or not me["alive"]:
        _print_debrief(me)
        return None
    if hp < 0.3 * max_hp:
        inv = {i["item_id"]: i for i in me["inventory"]}
        if "itm_healing_potion" in inv:
            return ("use_item", {"item_id": "itm_healing_potion"})
        return ("rest", {})
    here_npcs = {n["npc_id"] for n in world.get("npcs", [])}
    done_ids = set(completed or []) | {q.get("quest_id") for q in (me.get("completed_quests") or [])}
    active = [q for q in (me.get("active_quests") or []) if isinstance(q, dict)]
    # finished quests must be returned IN PERSON: check in via talk, then turn in
    for q in active:
        if not _quest_complete(q):
            continue
        qid, home = q.get("quest_id"), q.get("turn_in_at", "")
        giver = q.get("giver_npc", "") or QUEST_META.get(qid, {}).get("giver_npc", "")
        if home and me.get("location") != home:
            continue  # walk back below
        if giver and giver in here_npcs:
            if q.get("ready_talk"):
                return ("turn_in_quest", {"quest_id": qid})
            return ("talk_to_npc", {"npc_id": giver})
        if q.get("ready_talk"):
            return ("turn_in_quest", {"quest_id": qid})
        if world.get("npcs"):
            return ("talk_to_npc", {"npc_id": world["npcs"][0]["npc_id"]})
    # holding a complete quest but standing elsewhere: head back (directed)
    for q in active:
        if _quest_complete(q) and q.get("turn_in_at") and q.get("turn_in_at") != me.get("location"):
            step = _move_toward(q["turn_in_at"], world, zones)
            if step:
                return step
    # COMBAT FIRST: never walk away from local prey at healthy HP
    if world.get("monsters"):
        need_names = set()
        for q in active:
            if not _quest_complete(q):
                meta = QUEST_META.get(q.get("quest_id", ""), {})
                if meta.get("item_id"):
                    need_names.add(meta["item_id"])
        # world monster rows carry drops.item name, not item_id; match loosely
        # via QUEST_META item names when possible, else weakest first
        def _score(m):
            drop = (m.get("drops") or {}).get("name", "")
            for q in active:
                meta = QUEST_META.get(q.get("quest_id", ""), {})
                # item_id suffix (rat_pelt) vs drop name (Rat Pelt): compare words
                iid = meta.get("item_id", "")
                if iid and drop and iid.split("itm_")[-1].replace("_", " ") in drop.lower():
                    return (0, m["hp"])
            return (1, m["hp"])
        m = sorted(world["monsters"], key=_score)[0]
        return ("attack", {"target_id": m["monster_id"]})
    if world.get("items_on_ground"):
        # prioritize quest items lying around
        need_ids = {QUEST_META[q.get("quest_id", "")].get("item_id")
                    for q in active if q.get("quest_id") in QUEST_META}
        for g in world["items_on_ground"]:
            if g.get("item_id") in need_ids:
                return ("pick_up", {"item_id": g["item_id"]})
        return ("pick_up", {"item_id": world["items_on_ground"][0]["item_id"]})
    # accept ONLY offers whose giver is actually here (location+talk rule);
    # stale offers from other towns are ignored instead of bouncing remotely.
    # The server allows one unfinished quest, so never spend a turn asking for
    # a second one while the current quest is still active.
    by_id = {}
    for q in offered:
        if isinstance(q, dict) and q.get("quest_id"):
            by_id[q["quest_id"]] = q
    for qid, q in by_id.items():
        giver = q.get("giver") or q.get("giver_npc") or QUEST_META.get(qid, {}).get("giver_npc", "")
        ok = q.get("level_ok", True)
        done = q.get("completed", False) or q.get("status") == "completed"
        if (qid not in accepted and qid not in done_ids and ok and not done
                and not active and giver in here_npcs):
            return ("accept_quest", {"quest_id": qid})
    # have incomplete quests but nothing to fight here — go to the hunt ground
    for q in active:
        if not _quest_complete(q):
            hunt = QUEST_META.get(q.get("quest_id", ""), {}).get("hunt")
            if hunt and hunt != me.get("location"):
                step = _move_toward(hunt, world, zones)
                if step:
                    return step
            if world.get("exits"):
                return ("move", {"to": world["exits"][0]["to"]})
    # no quests: grind XP or walk to the next unlocked giver — never idle-talk
    if not active:
        level = me.get("level", 1)
        # next reachable quest giver at our level we haven't done
        for qid, meta in sorted(QUEST_META.items(), key=lambda kv: kv[1]["min_level"]):
            if qid in accepted or qid in done_ids or level < meta["min_level"]:
                continue
            if meta["giver_loc"] == me.get("location"):
                # standing with an untried giver but never talked: talk once
                if meta["giver_npc"] in here_npcs and meta["giver_npc"] not in _recent_talk_npcs(recent):
                    return ("talk_to_npc", {"npc_id": meta["giver_npc"]})
            # otherwise walk toward that giver to find work
            step = _move_toward(meta["giver_loc"], world, zones)
            if step:
                return step
        # nothing unlocked (e.g. Lv1 after ratcatcher, wolfpack needs Lv2):
        # grind the level-appropriate hunting ground until we level up
        grind = GRIND_BY_LEVEL.get(min(level, 5), "oakhollow_forest")
        if grind != me.get("location"):
            step = _move_toward(grind, world, zones)
            if step:
                return step
        # already at the grind spot but it is empty (respawn gap): wait via
        # scout/say instead of pestering NPCs, or hop to the neighbor
        if world.get("exits"):
            return ("move", {"to": world["exits"][0]["to"]})
    # talk only when useful: an untried NPC here while questless/handing in
    if world.get("npcs"):
        talked = set(_recent_talk_npcs(recent))
        for n in world["npcs"]:
            if n["npc_id"] not in talked:
                # only talk if that NPC could offer something new
                offers_here = [o for o in by_id.values()
                               if (o.get("giver") or QUEST_META.get(o.get("quest_id", ""), {}).get("giver_npc")) == n["npc_id"]]
                if not offers_here:
                    return ("talk_to_npc", {"npc_id": n["npc_id"]})
                for o in offers_here:
                    if (o.get("quest_id") not in accepted and o.get("quest_id") not in done_ids
                            and o.get("status") in (None, "available")):
                        return ("talk_to_npc", {"npc_id": n["npc_id"]})
    if world.get("exits"):
        return ("move", {"to": world["exits"][0]["to"]})
    return ("say", {"message": "Onward."})
