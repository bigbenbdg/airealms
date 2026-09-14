"""AI Realms game server — FastAPI. Implements 02-api-spec.md v1."""
import json
import secrets
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, Depends, Header, HTTPException, Request, Query, WebSocket, WebSocketDisconnect, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse
from sqlalchemy.orm import Session
from sqlalchemy import desc

from .db import Base, engine, get_db, SessionLocal, ensure_schema
from .models import Agent, Monster, GroundItem, WorldEvent, utcnow
from .seed import (LOCATIONS, EDGES, NPCS, QUESTS, SHOP, STARTER_INVENTORY,
                   MERCHANT_ID, ARMORER_STOCK, MERCHANT_BUYBACK,
                   merchant_npc, shop_for, buys_for, stock_spec, sell_price,
                   seed_monsters, seed_ground, exits_from, loc_by_id, quest_brief, roll_drop,
                   MONSTER_DROPS, ground_item_props, danger_of, quests_at, monster_haunts,
                   monster_for_item)
from .engine import (ACTION_DEFS, check_rate_limit, check_idempotency, store_idempotency,
                     load_json, apply_xp, player_attack_damage, player_defense, monster_attack_damage,
                     set_cooldown, cooldown_remaining, manager, xp_for_level,
                     VILLAGE_REGEN_HP, respawn_due, REQUIRED_PARAMS)
from .goals import GOALS, realm_goal_text, death_report

ensure_schema()
try:
    _db = SessionLocal()
    seed_monsters(_db)
    seed_ground(_db)
    respawn_due(_db)
    _db.close()
except Exception:
    pass

app = FastAPI(title="AI Realms", version="1.0.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

SKILL_PATH = Path(__file__).resolve().parents[2] / "03-SKILLS.md"
_skill_cache = None


def skill_text():
    global _skill_cache
    if _skill_cache is None:
        _skill_cache = SKILL_PATH.read_text(encoding="utf-8") if SKILL_PATH.exists() else "# AI Realms\n"
    return _skill_cache


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def ok(data, narrative=""):
    return {"ok": True, "narrative": narrative, "data": data, "server_time": now_iso()}


def err(code, message, retry_after=None, status=400):
    body = {"ok": False, "error": {"code": code, "message": message}, "server_time": now_iso()}
    if retry_after is not None:
        body["error"]["retry_after_seconds"] = retry_after
    raise HTTPException(status_code=status, detail=body)


def get_agent(authorization: str = Header(default=""), db: Session = Depends(get_db)) -> Agent:
    if not authorization.startswith("Bearer "):
        err("INVALID_API_KEY", "Missing Authorization: Bearer <api_key> header.", status=401)
    key = authorization[len("Bearer "):].strip()
    if not check_rate_limit(f"key:{key}"):
        err("RATE_LIMITED", "Slow down: 1 request/sec sustained (burst 5).", status=429)
    agent = db.query(Agent).filter(Agent.api_key == key).first()
    if not agent:
        err("INVALID_API_KEY", "Unknown API key.", status=401)
    return agent


def emit(db: Session, type_: str, agent_name="", agent_id="", detail=""):
    ev = WorldEvent(type=type_, agent=agent_name, agent_id=agent_id, detail=detail, at=utcnow())
    db.add(ev)
    db.commit()
    db.refresh(ev)
    payload = {"id": f"evt_{ev.id}", "type": ev.type, "agent": ev.agent,
               "detail": ev.detail, "at": ev.at.isoformat()}
    return payload


async def fanout(payload: dict):
    await manager.broadcast(payload)


def _quest_have(inv: list, spec: dict) -> int:
    """Total qty of the quest's required item held in inventory."""
    need = spec.get("item_id", "")
    return sum(i.get("qty", 0) for i in inv if i.get("item_id") == need)


def _quest_progress(inv: list, spec: dict) -> str:
    have = _quest_have(inv, spec)
    return f"{min(have, spec['count'])}/{spec['count']} {spec['item_name']} delivered"


def _quest_hint(spec: dict) -> str:
    """Where to find the required items, e.g. 'Forest Wolf in Oakhollow Forest (60% drop)'."""
    source = monster_for_item(spec.get("item_id", ""))
    if not source:
        return "the wilds"
    where = ", ".join(monster_haunts(source)) or "the wilds"
    chance = MONSTER_DROPS.get(source, {}).get("chance")
    odds = f" ({int(chance * 100)}% drop)" if chance is not None else ""
    return f"{source} in {where}{odds}"


def _giver_npc(quest_id: str):
    """The NPC dict that gives quest_id, or None."""
    spec = QUESTS.get(quest_id)
    if not spec:
        return None
    return next((n for n in NPCS if n["npc_id"] == spec["giver"]), None)


def _giver_place_name(quest_id: str) -> str:
    npc = _giver_npc(quest_id)
    if not npc:
        return "somewhere"
    loc = loc_by_id(npc["location"])
    return loc["name"] if loc else npc["location"]


def _talk_map(agent) -> dict:
    """Per-NPC talk memory: {npc_id: {location, at}}. Tolerant of legacy shape."""
    try:
        raw = load_json(getattr(agent, "talk_state", None) or "{}", {})
    except Exception:
        return {}
    if not isinstance(raw, dict):
        return {}
    # legacy single-talk shape {"npc_id":..., "location":..., "at":...}
    if "npc_id" in raw and isinstance(raw.get("npc_id"), str):
        nid = raw["npc_id"]
        return {nid: {"location": raw.get("location", ""), "at": raw.get("at", "")}}
    out = {}
    for k, v in raw.items():
        if isinstance(v, dict):
            out[k] = {"location": v.get("location", ""), "at": v.get("at", "")}
    return out


def _save_talk_map(agent, talk: dict):
    try:
        agent.talk_state = json.dumps(talk)
    except Exception:
        pass


def _talked_here(agent, npc_id: str) -> bool:
    talk = _talk_map(agent)
    entry = talk.get(npc_id)
    return bool(entry) and entry.get("location") == agent.location


def _require_giver_presence(agent, quest_id: str, purpose: str):
    """Enforce return-to-giver: must stand where the giver NPC is and have
    talked to them there. Raises WRONG_LOCATION / TALK_FIRST."""
    spec = QUESTS.get(quest_id)
    npc = _giver_npc(quest_id)
    if not spec or not npc:
        return
    place = _giver_place_name(quest_id)
    if agent.location != npc["location"]:
        err("WRONG_LOCATION",
            f"'{spec['title']}' {purpose} must happen at {place}: "
            f"find {npc['name']} ({npc['npc_id']}) there and talk_to_npc first.")
    if not _talked_here(agent, npc["npc_id"]):
        err("TALK_FIRST",
            f"Talk to {npc['name']} ({npc['npc_id']}) here first "
            f"(talk_to_npc), then {purpose}.")


def agent_public(a: Agent):
    return {"agent_id": a.id, "name": a.name, "bio": a.bio, "level": a.level,
            "hp": a.hp, "max_hp": a.max_hp,
            "location_public": a.location, "kills": a.kills,
            "quests_completed": a.quests_completed, "alive": a.alive,
            "registered_at": a.registered_at.isoformat() if a.registered_at else None}


# ---------- meta ----------
@app.get("/api/v1/meta/skill")
def meta_skill(format: str = Query(default="md")):
    text = skill_text()
    if format == "json":
        return ok({"content": text}, "AI Realms player skill (JSON variant).")
    return PlainTextResponse(text, media_type="text/markdown")


@app.get("/api/v1/meta/goals")
def meta_goals():
    """Server-authoritative objectives. Every agent should read this before playing."""
    return ok({"realm_goal": GOALS["realm_goal"], "objectives": GOALS["objectives"],
               "how_to_win": GOALS["how_to_win"], "starter_path": GOALS["starter_path"],
               "death_policy": GOALS["death_policy"]},
              "The objectives every agent plays toward. Point your LLM brain at these.")


@app.get("/api/v1/actions/schema")
def actions_schema():
    return ok({"actions": ACTION_DEFS}, "Machine-readable action catalog.")


# ---------- register ----------
@app.post("/api/v1/agents/register")
def register(body: dict, request: Request, db: Session = Depends(get_db)):
    ip = request.client.host if request.client else "unknown"
    if not check_rate_limit(f"reg:{ip}"):
        err("RATE_LIMITED", "Too many registrations from this IP.", status=429)
    # simple per-IP daily cap via in-memory is skipped; enforce burst limit above + count check
    recent = db.query(WorldEvent).filter(WorldEvent.type == "register").count()
    _ = recent  # placeholder for audit log size
    name = str(body.get("display_name", "Nameless Wanderer"))[:40]
    bio = str(body.get("bio", ""))[:200]
    owner = str(body.get("owner_contact", ""))[:120]
    if not name.strip():
        err("INVALID_PARAMS", "display_name must not be empty.")
    agent_id = "agt_" + secrets.token_hex(4)
    api_key = "sk_live_" + secrets.token_hex(16)
    a = Agent(id=agent_id, api_key=api_key, name=name.strip(), bio=bio,
              owner_contact=owner, location="riverside_village",
              inventory=json.dumps(STARTER_INVENTORY))
    db.add(a)
    seed_monsters(db)
    seed_ground(db)
    payload = emit(db, "register", name, agent_id, f"{name} entered the realm at Riverside Village.")
    db.commit()
    import asyncio
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        pass
    return ok({"agent_id": agent_id, "api_key": api_key,
               "starting_location": "riverside_village",
               "note": "Store this api_key now — it will not be shown again."},
              f"Welcome, {name}! You wake up in Riverside Village with a rusty sword and a healing potion.")


# ---------- private state ----------
@app.get("/api/v1/status")
def status(agent: Agent = Depends(get_agent), db: Session = Depends(get_db)):
    inv = load_json(agent.inventory, [])
    quests = load_json(agent.quests, [])
    report = death_report(agent, db) if not agent.alive else None
    narrative = f"{agent.name}, level {agent.level}, {agent.hp}/{agent.max_hp} HP at {agent.location}."
    if report:
        narrative = (f"{agent.name} is dead — slain by {report['killed_by']}. "
                     f"Top lesson: {report['lessons'][1]}")
    return ok({
        "agent_id": agent.id, "name": agent.name, "level": agent.level, "xp": agent.xp,
        "xp_to_next_level": xp_for_level(agent.level), "hp": agent.hp, "max_hp": agent.max_hp,
        "stats": load_json(agent.stats, {}), "gold": agent.gold, "location": agent.location,
        "status_effects": [], "inventory": inv,
        "active_quests": [{"quest_id": q["quest_id"], "title": q["title"],
                           "progress": _quest_progress(inv, QUESTS[q["quest_id"]]),
                           "giver_npc": QUESTS[q["quest_id"]].get("giver"),
                           "giver_name": (_giver_npc(q["quest_id"]) or {}).get("name", ""),
                           "turn_in_at": ((_giver_npc(q["quest_id"]) or {}).get("location", "")),
                           "ready_talk": bool(q.get("ready_talk"))}
                          for q in quests if not q.get("done") and q["quest_id"] in QUESTS],
        "completed_quests": [{"quest_id": q["quest_id"], "title": q["title"],
                              "completed_at": q.get("completed_at")}
                             for q in quests if q.get("done")],
        "cooldown_seconds_remaining": cooldown_remaining(agent), "alive": agent.alive,
        "death_report": report,
    }, narrative)


@app.get("/api/v1/world/here")
def world_here(agent: Agent = Depends(get_agent), db: Session = Depends(get_db)):
    respawn_due(db, agent.location)
    loc = loc_by_id(agent.location)
    if not loc:
        err("TARGET_NOT_FOUND", f"Unknown location {agent.location}.")
    npcs = [n for n in NPCS if n["location"] == agent.location]
    monsters = [{"monster_id": m.id, "name": m.name, "hp": m.hp, "max_hp": m.max_hp,
                 "drops": ({"name": MONSTER_DROPS[m.name]["name"],
                            "chance": MONSTER_DROPS[m.name]["chance"]}
                           if m.name in MONSTER_DROPS else None)}
                for m in db.query(Monster).filter(Monster.location == agent.location, Monster.alive == True).all()]  # noqa: E712
    others = db.query(Agent).filter(Agent.location == agent.location, Agent.id != agent.id).all()
    ground = [{"ground_id": g.id, "item_id": g.item_id, "name": g.name, "qty": g.qty}
              for g in db.query(GroundItem).filter(GroundItem.location == agent.location).all()]
    narrative = f"You are in {loc['name']}. {loc['description']}"
    if loc.get("type") == "town":
        narrative += f" Safe ground: every action you take here restores +{VILLAGE_REGEN_HP} HP."
    return ok({"location_id": loc["id"], "description": loc["description"],
               "exits": exits_from(loc["id"]), "npcs": npcs, "monsters": monsters,
               "agents_present": [{"agent_id": o.id, "name": o.name, "level": o.level} for o in others],
               "items_on_ground": ground},
              narrative)


@app.get("/api/v1/world/map")
def world_map():
    return ok({"locations": [{"id": l["id"], "name": l["name"], "type": l["type"]} for l in LOCATIONS],
               "edges": EDGES}, "The known world: 6 locations linked by road and trail.")


def zone_snapshot(db: Session, loc):
    """Full intel for one place: quests, NPCs, monsters, loot, players, exits."""
    agents = [{"agent_id": a.id, "name": a.name, "level": a.level,
               "hp": a.hp, "max_hp": a.max_hp, "alive": a.alive}
              for a in db.query(Agent).filter(Agent.location == loc["id"]).all()]
    monsters = []
    for m in db.query(Monster).filter(Monster.location == loc["id"], Monster.alive == True).all():  # noqa: E712
        drop = MONSTER_DROPS.get(m.name)
        monsters.append({"monster_id": m.id, "name": m.name, "hp": m.hp,
                         "max_hp": m.max_hp,
                         "drops": ({"name": drop["name"], "chance": drop["chance"]}
                                   if drop else None)})
    loot = [{"ground_id": g.id, "item_id": g.item_id, "name": g.name, "qty": g.qty}
            for g in db.query(GroundItem).filter(GroundItem.location == loc["id"]).all()]
    return {"id": loc["id"], "name": loc["name"], "type": loc["type"],
            "description": loc["description"],
            "danger": danger_of(loc["id"]),
            "exits": exits_from(loc["id"]),
            "agents": agents, "monsters": monsters, "loot": loot,
            "npcs": [{"npc_id": n["npc_id"], "name": n["name"],
                      "can_trade": n["can_trade"], "has_quest": n["has_quest"]}
                     for n in NPCS if n["location"] == loc["id"]],
            "quests": quests_at(loc["id"])}


@app.get("/api/v1/world/state")
def world_state(db: Session = Depends(get_db)):
    """Bulk intel snapshot: every place on the map with its quests, NPCs,
    monsters, ground loot, players present, and exits — one call so a player
    (or spectator) can decide what to do in each place. Public, read-only."""
    respawn_due(db)
    zones = [zone_snapshot(db, loc) for loc in LOCATIONS]
    return ok({"zones": zones}, "Every place at a glance: quests, NPCs, monsters, loot, players, exits.")


# ---------- actions ----------
@app.post("/api/v1/actions")
async def do_action(body: dict, request: Request, agent: Agent = Depends(get_agent),
                    db: Session = Depends(get_db)):
    idem = request.headers.get("Idempotency-Key", "")
    if idem:
        cached = check_idempotency(f"{agent.id}:{idem}")
        if cached is not None:
            return cached
    action = body.get("action", "")
    params = body.get("params", {}) or {}
    if action not in [a["name"] for a in ACTION_DEFS]:
        err("INVALID_ACTION", f"Unknown action '{action}'. See GET /actions/schema.")
    missing = [p for p in REQUIRED_PARAMS.get(action, []) if not params.get(p)]
    if missing:
        err("INVALID_PARAMS", f"Action '{action}' is missing required param(s): "
                              f"{', '.join(missing)}. See GET /actions/schema.")
    if not agent.alive:
        rep = death_report(agent, db)
        hint = f" Debrief: {rep['lessons'][1]}" if rep else " Check GET /status for a death debrief."
        err("AGENT_DEAD", f"You are dead.{hint}", status=409)
    rem = cooldown_remaining(agent)
    if rem > 0:
        err("COOLDOWN_ACTIVE", f"You can't act again for {rem} more seconds.", retry_after=rem, status=429)

    db_agent = db.query(Agent).filter(Agent.id == agent.id).first()
    respawn_due(db, db_agent.location)
    result, narrative = _apply_action(db, db_agent, action, params)
    # Village regeneration: safe ground restores +5 HP per completed action.
    regen = 0
    here_loc = loc_by_id(db_agent.location)
    if here_loc and here_loc.get("type") == "town" and db_agent.alive and db_agent.hp < db_agent.max_hp:
        regen = min(VILLAGE_REGEN_HP, db_agent.max_hp - db_agent.hp)
        db_agent.hp += regen
    if regen:
        result["hp_regen"] = regen
        narrative += f" The safety of {here_loc['name']} restores you (+{regen} HP)."
    secs = set_cooldown(db_agent, action)
    if isinstance(result, dict) and "cooldown_seconds" not in result:
        result["cooldown_seconds"] = secs
    # Player snapshot on every turn: level, XP, HP, gold and quest counts ride
    # along so the brain never needs a separate /status call to see progress.
    result["player"] = {
        "level": db_agent.level, "xp": db_agent.xp,
        "xp_to_next_level": xp_for_level(db_agent.level),
        "hp": db_agent.hp, "max_hp": db_agent.max_hp, "gold": db_agent.gold,
        "kills": db_agent.kills, "quests_completed": db_agent.quests_completed,
        "location": db_agent.location, "alive": db_agent.alive,
        "cooldown_seconds_remaining": cooldown_remaining(db_agent),
    }
    db.commit()
    for evt in _pending_events(db):
        await fanout(evt)
    resp = ok({"action": action, **result}, narrative)
    store_idempotency(f"{agent.id}:{idem}", resp)
    return resp


_pending: list = []


def _pending_events(db):
    global _pending
    out = _pending
    _pending = []
    return out


def _queue(payload):
    _pending.append(payload)


def _apply_action(db, agent, action, params):
    inv = load_json(agent.inventory, [])
    quests = load_json(agent.quests, [])

    def save_inv():
        agent.inventory = json.dumps(inv)

    def save_quests():
        agent.quests = json.dumps(quests)

    if action == "move":
        to = params.get("to", "")
        valid = [e["to"] for e in exits_from(agent.location)]
        if to not in valid:
            err("INVALID_PARAMS", f"'{to}' is not reachable from {agent.location}. Exits: {valid}.")
        agent.location = to
        loc = loc_by_id(to)
        # Arrival notification: tell the player everyone of note in this map —
        # all NPCs (with roles + IDs for talk_to_npc) plus headcounts of
        # monsters, loot piles, and other agents, so one move is enough to
        # decide the next turn without a follow-up world/here call.
        respawn_due(db, to)
        npcs_here = [n for n in NPCS if n["location"] == to]
        if npcs_here:
            bits = []
            for n in npcs_here:
                roles = []
                if n.get("has_quest"):
                    roles.append("quest-giver")
                if n.get("can_trade"):
                    roles.append("merchant")
                role = f" ({', '.join(roles)})" if roles else ""
                bits.append(f"{n['name']}{role} [{n['npc_id']}]")
            npc_line = " People here: " + "; ".join(bits) + ". Talk to them with talk_to_npc."
        else:
            npc_line = " No NPCs here."
        from .models import Monster as _Mon, GroundItem as _GI, Agent as _Ag
        n_mon = db.query(_Mon).filter(_Mon.location == to, _Mon.alive == True).count()  # noqa: E712
        n_loot = db.query(_GI).filter(_GI.location == to).count()
        n_agents = db.query(_Ag).filter(_Ag.location == to, _Ag.id != agent.id).count()
        headcounts = f" Also here: {n_mon} monster(s), {n_loot} loot pile(s), {n_agents} other agent(s)."
        return {"result": "moved", "location": to, "npcs": npcs_here,
                "monsters_present": n_mon, "loot_piles": n_loot,
                "agents_present": n_agents}, \
               f"You travel to {loc['name']}. {loc['description']}{npc_line}{headcounts}"

    if action == "scout":
        to = params.get("to", "")
        valid = [e["to"] for e in exits_from(agent.location)]
        if to not in valid:
            err("INVALID_PARAMS", f"'{to}' is not adjacent to {agent.location}. Exits: {valid}.")
        target = loc_by_id(to)
        if not target:
            err("TARGET_NOT_FOUND", f"Unknown location '{to}'.")
        respawn_due(db, to)
        snap = zone_snapshot(db, target)
        foes = ", ".join(f"{m['name']} ({m['hp']} HP)" for m in snap["monsters"]) or "no monsters"
        work = "; ".join(f"{q['title']} [{q['quest_id']}]" for q in snap["quests"]) or "no quests"
        others = f"{len(snap['agents'])} other agent(s)" if snap["agents"] else "no other agents"
        piles = f"{len(snap['loot'])} loot pile(s)" if snap["loot"] else "no loot"
        return {"result": "scouted", "location": to, "intel": snap}, \
               (f"You scout {target['name']} from afar: {snap['danger']} {target['type']}. "
                f"Foes: {foes}. Work: {work}. {others}, {piles} on the ground.")

    if action == "attack":
        tid = params.get("target_id", "")
        m = db.query(Monster).filter(Monster.id == tid, Monster.alive == True).first()  # noqa: E712
        if not m or m.location != agent.location:
            # PvP stub: refuse politely
            rival = db.query(Agent).filter(Agent.id == tid).first()
            if rival and rival.location == agent.location and rival.alive:
                err("INVALID_ACTION", "PvP is disabled in v1 arenas. Fight monsters instead.")
            err("TARGET_NOT_FOUND", f"No living target '{tid}' here.")
        dmg = player_attack_damage(agent)
        m.hp -= dmg
        ret = 0
        msg = f"You swing at the {m.name} for {dmg} damage."
        if m.hp <= 0:
            m.hp = 0
            m.alive = False
            m.died_at = utcnow()
            agent.gold += m.gold_reward
            agent.kills += 1
            # Quest progress is purely item-based (see turn_in_quest): kills only
            # matter insofar as they drop the required items.
            leveled = apply_xp(agent, m.xp_reward)
            drop = roll_drop(m.name)
            loot_items = []
            if drop:
                have = next((i for i in inv if i["item_id"] == drop["item_id"]), None)
                if have:
                    have["qty"] = have.get("qty", 0) + 1
                else:
                    inv.append(drop)
                save_inv()
                loot_items = [{"item_id": drop["item_id"], "name": drop["name"], "qty": 1}]
            detail = f"slew a {m.name} (+{m.xp_reward} XP, +{m.gold_reward} gold)"
            if loot_items:
                detail += f", looted {loot_items[0]['name']}"
            _queue(emit(db, "combat", agent.name, agent.id, f"{agent.name} {detail}."))
            if leveled:
                _queue(emit(db, "level_up", agent.name, agent.id, f"{agent.name} reached level {agent.level}."))
                msg += f" It falls! +{m.xp_reward} XP, +{m.gold_reward} gold. LEVEL UP — you are now level {agent.level}!"
            else:
                msg += f" It falls! +{m.xp_reward} XP, +{m.gold_reward} gold."
            if loot_items:
                msg += f" It drops {loot_items[0]['name']} — auto-looted to your inventory (no pick_up needed)!"
            return {"result": "kill", "damage_dealt": dmg, "damage_taken": 0,
                    "target_hp_remaining": 0, "self_hp_remaining": agent.hp,
                    "xp_gained": m.xp_reward,
                    "loot": {"gold": m.gold_reward, "items": loot_items}}, msg
        ret = max(1, monster_attack_damage(m) - player_defense(agent))
        agent.hp -= ret
        if agent.hp <= 0:
            agent.hp = 0
            agent.alive = False
            _queue(emit(db, "death", agent.name, agent.id, f"{agent.name} was slain by a {m.name}."))
            return {"result": "death", "damage_dealt": dmg, "damage_taken": ret,
                    "target_hp_remaining": m.hp, "self_hp_remaining": 0,
                    "xp_gained": 0, "loot": None}, f"You hit the {m.name} for {dmg}, but it strikes back for {ret}. You die."
        msg += f" It bites back for {ret}. The {m.name} has {m.hp} HP left."
        return {"result": "hit", "damage_dealt": dmg, "damage_taken": ret,
                "target_hp_remaining": m.hp, "self_hp_remaining": agent.hp,
                "xp_gained": 0, "loot": None}, msg

    if action == "flee":
        exits = exits_from(agent.location)
        if not exits:
            err("INVALID_ACTION", "There's nowhere to flee to.")
        agent.location = exits[0]["to"]
        return {"result": "fled", "location": agent.location}, f"You flee to {loc_by_id(agent.location)['name']}."

    if action == "use_item":
        iid = params.get("item_id", "")
        item = next((i for i in inv if i["item_id"] == iid and i.get("qty", 0) > 0), None)
        if not item:
            err("TARGET_NOT_FOUND", f"You don't have '{iid}'.")
        if "heal" in item:
            agent.hp = min(agent.max_hp, agent.hp + item["heal"])
            item["qty"] -= 1
            if item["qty"] <= 0:
                inv.remove(item)
            save_inv()
            return {"result": "healed", "self_hp_remaining": agent.hp}, f"You quaff a {item['name']} (+{item['heal']} HP). Now at {agent.hp}/{agent.max_hp}."
        err("INVALID_PARAMS", f"{item['name']} can't be used that way. Try equip_item.")

    if action == "equip_item":
        iid = params.get("item_id", "")
        item = next((i for i in inv if i["item_id"] == iid), None)
        if not item:
            err("TARGET_NOT_FOUND", f"You don't have '{iid}'.")
        if item.get("bonus"):
            # Weapon slot: one blade at a time; armor stays equipped.
            for i in inv:
                if i.get("bonus"):
                    i["equipped"] = (i["item_id"] == iid)
        elif item.get("defense"):
            # Armor slot: one plate at a time; weapon stays equipped.
            for i in inv:
                if i.get("defense"):
                    i["equipped"] = (i["item_id"] == iid)
        elif item.get("max_hp_bonus"):
            # Legacy armor (pre-tiered Leather Armor): consume into max HP.
            agent.max_hp += item["max_hp_bonus"]
            item.pop("max_hp_bonus")
            item["equipped"] = True
        else:
            err("INVALID_PARAMS", f"{item['name']} isn't equippable. Equip a weapon (+ATK) or armor (+DEF).")
        save_inv()
        return {"result": "equipped", "item_id": iid}, f"You equip the {item['name']}."

    if action == "buy_item":
        nid = params.get("npc_id", "")
        iid = params.get("item_id", "")
        npc = next((n for n in NPCS if n["npc_id"] == nid), None)
        if npc is None or nid != MERCHANT_ID:
            merch = merchant_npc()
            where = loc_by_id(merch["location"])["name"] if merch else "the Capital City"
            who = f"{merch['name']} ({MERCHANT_ID})" if merch else "the merchant"
            err("TARGET_NOT_FOUND", f"'{nid or '???'}' doesn't trade. All commerce is exclusive "
                                    f"to {who} in {where}: talk_to_npc there, then buy_item.")
        spec = stock_spec(iid)
        if not spec:
            err("TARGET_NOT_FOUND", f"'{iid}' is not in {npc['name']}'s stock. "
                                    f"Check talk_to_npc shop first.")
        if agent.location != npc["location"]:
            place = loc_by_id(npc["location"])
            pname = place["name"] if place else npc["location"]
            err("WRONG_LOCATION", f"Buying must happen at {pname}: find {npc['name']} "
                                  f"({nid}) there and talk_to_npc first.")
        if not _talked_here(agent, nid):
            err("TALK_FIRST", f"Talk to {npc['name']} ({nid}) here first "
                              f"(talk_to_npc), then buy_item.")
        need = spec.get("min_level", 1)
        if agent.level < need:
            err("QUEST_LOCKED", f"'{spec['name']}' requires level {need} (you are level {agent.level}). "
                                f"Level up first — try easier quests or weaker monsters.", status=403)
        price = spec["price"]
        if agent.gold < price:
            err("NOT_ENOUGH_GOLD", f"'{spec['name']}' costs {price} gold, you hold {agent.gold}. "
                                   f"Earn more: sell surplus trophies or finish quests.")
        agent.gold -= price
        entry = {"item_id": spec["item_id"], "name": spec["name"],
                 "qty": 1, "equipped": False}
        for k in ("bonus", "defense", "heal", "kind"):
            if k in spec:
                entry[k] = spec[k]
        have = next((i for i in inv if i["item_id"] == iid), None)
        if have:
            have["qty"] = have.get("qty", 0) + 1
            # bought copies arrive unequipped; keep existing equip state
            for k in ("bonus", "defense", "heal", "kind", "name"):
                if k in entry:
                    have.setdefault(k, entry[k])
        else:
            inv.append(entry)
        save_inv()
        _queue(emit(db, "loot", agent.name, agent.id,
                    f"{agent.name} bought {spec['name']} for {price} gold."))
        return {"result": "bought", "item_id": iid, "price": price,
                "gold_remaining": agent.gold}, \
               f"You buy {spec['name']} for {price} gold ({agent.gold} left). Equip it with equip_item."

    if action == "sell_item":
        nid = params.get("npc_id", "")
        iid = params.get("item_id", "")
        try:
            qty = int(params.get("qty", 1))
        except (TypeError, ValueError):
            err("INVALID_PARAMS", "qty must be an integer.")
        if qty < 1:
            err("INVALID_PARAMS", "qty must be at least 1.")
        npc = next((n for n in NPCS if n["npc_id"] == nid), None)
        if npc is None or nid != MERCHANT_ID:
            merch = merchant_npc()
            where = loc_by_id(merch["location"])["name"] if merch else "the Capital City"
            who = f"{merch['name']} ({MERCHANT_ID})" if merch else "the merchant"
            err("TARGET_NOT_FOUND", f"'{nid or '???'}' doesn't trade. All commerce is exclusive "
                                    f"to {who} in {where}: talk_to_npc there, then sell_item.")
        price = sell_price(iid)
        if price is None:
            err("TARGET_NOT_FOUND", f"{npc['name']} doesn't buy '{iid}'. She buys monster trophies "
                                    f"(pelts, daggers, hides, essences, scales) and used weapons/armor "
                                    f"(half the buy price) — check talk_to_npc buys.")
        if agent.location != npc["location"]:
            place = loc_by_id(npc["location"])
            pname = place["name"] if place else npc["location"]
            err("WRONG_LOCATION", f"Selling must happen at {pname}: find {npc['name']} "
                                  f"({nid}) there and talk_to_npc first.")
        if not _talked_here(agent, nid):
            err("TALK_FIRST", f"Talk to {npc['name']} ({nid}) here first "
                              f"(talk_to_npc), then sell_item.")
        have_qty = sum(i.get("qty", 0) for i in inv if i.get("item_id") == iid)
        if have_qty < qty:
            err("INVALID_PARAMS", f"You hold {have_qty}x '{iid}', can't sell {qty}.")
        # Quest block: anything an active quest needs can't be sold at all —
        # finish the quest first, then the leftovers are fair game.
        # (Completed quests don't block.)
        for q in quests:
            if q.get("done"):
                continue
            spec = QUESTS.get(q.get("quest_id", ""))
            if spec and spec.get("item_id") == iid:
                err("INVALID_PARAMS", f"'{spec['item_name']}' is needed for your active quest "
                                      f"'{spec['title']}': finish it first, then sell the rest.")
        # Consume unequipped copies first, then equipped (as with quest turn-ins).
        need = qty
        for item in sorted(inv, key=lambda i: bool(i.get("equipped"))):
            if need <= 0:
                break
            if item.get("item_id") != iid:
                continue
            take = min(item.get("qty", 0), need)
            item["qty"] -= take
            need -= take
        inv[:] = [i for i in inv if i.get("qty", 0) > 0]
        save_inv()
        gain = price * qty
        agent.gold += gain
        iname = next((s["name"] for s in buys_for(nid) if s["item_id"] == iid), iid)
        _queue(emit(db, "loot", agent.name, agent.id,
                    f"{agent.name} sold {qty}x {iname} for {gain} gold."))
        return {"result": "sold", "item_id": iid, "qty": qty,
                "gold_gained": gain, "gold_total": agent.gold}, \
               f"You sell {qty}x {iname} for {gain} gold (now {agent.gold})."

    if action == "pick_up":
        iid = params.get("item_id", "")
        g = db.query(GroundItem).filter(GroundItem.location == agent.location,
                                        GroundItem.item_id == iid).first()
        if not g:
            err("TARGET_NOT_FOUND", f"No '{iid}' lying here. Check world/here items_on_ground.")
        props = ground_item_props(iid) or {"item_id": g.item_id, "name": g.name, "qty": 1}
        have = next((i for i in inv if i["item_id"] == iid), None)
        if have:
            have["qty"] = have.get("qty", 0) + g.qty
        else:
            inv.append({**props, "qty": g.qty, "equipped": False})
        db.delete(g)
        save_inv()
        return {"result": "picked_up", "item_id": iid, "qty": g.qty}, \
               f"You pick up {g.qty}x {g.name}."

    if action == "talk_to_npc":
        nid = params.get("npc_id", "")
        npc = next((n for n in NPCS if n["npc_id"] == nid and n["location"] == agent.location), None)
        if not npc:
            err("TARGET_NOT_FOUND", f"No NPC '{nid}' here.")
        # Commerce is exclusive to the merchant: her talk shows the tiered
        # catalog (each entry flagged level_ok) plus trophy buyback prices;
        # every other NPC shows an empty shop.
        shop = [{**s, "level_ok": agent.level >= s.get("min_level", 1)}
                for s in shop_for(nid)]
        buys = buys_for(nid)
        offered = [q for qid, q in QUESTS.items() if q["giver"] == nid]
        mine = {q["quest_id"]: q for q in quests}
        lines, offers = [], []
        for qid in QUESTS:
            spec = QUESTS[qid]
            if spec["giver"] != nid:
                continue
            state = mine.get(qid)
            level_ok = agent.level >= spec.get("min_level", 1)
            if state and state.get("done"):
                status, note = "completed", (f"'{spec['title']}' is done — fine work, {agent.name}. ")
            elif state:
                status, note = "in_progress", (f"How goes '{spec['title']}'? {_quest_progress(inv, spec)} — "
                                               f"you'll find {_quest_hint(spec)}. "
                                               f"Bring the goods and turn_in_quest when you hold enough. ")
            elif not level_ok:
                status, note = "locked", (f"'{spec['title']}' [{qid}] needs level {spec.get('min_level', 1)} — "
                                          f"come back stronger. ")
            else:
                status, note = "available", f"{spec['title']} [{qid}]: {quest_brief(qid)} "
            lines.append(note)
            offers.append({"quest_id": qid, **spec, "level_ok": level_ok,
                           "completed": status == "completed", "status": status})
        # Point at other work when this NPC has nothing new for the player.
        if all(o["status"] != "available" for o in offers):
            tips = []
            for qid, spec in sorted(QUESTS.items(), key=lambda kv: kv[1].get("min_level", 1)):
                if spec["giver"] == nid:
                    continue
                st = mine.get(qid)
                if st:
                    continue  # taken or done — not news
                giver = next((n for n in NPCS if n["npc_id"] == spec["giver"]), None)
                gloc = loc_by_id(giver["location"])["name"] if giver and loc_by_id(giver["location"]) else "somewhere"
                tips.append(f"{giver['name'] if giver else 'Someone'} in {gloc} offers "
                            f"'{spec['title']}' (level {spec.get('min_level', 1)}+)")
                if len(tips) == 2:
                    break
            if tips:
                lines.append("For more work: " + " ".join(tips) + ". ")
        # Remember this visit: accepting and turning in quests requires
        # standing with the giver and having talked to them here. Talking
        # while holding enough items "checks in" the quest for turn-in.
        talk = _talk_map(agent)
        talk[nid] = {"location": agent.location, "at": now_iso()}
        _save_talk_map(agent, talk)
        checked_in = []
        for q in quests:
            spec = QUESTS.get(q.get("quest_id", ""))
            if not spec or spec.get("giver") != nid or q.get("done"):
                continue
            if _quest_have(inv, spec) >= spec["count"] and not q.get("ready_talk"):
                q["ready_talk"] = True
                checked_in.append(q["quest_id"])
        if checked_in:
            save_quests()
            for qid in checked_in:
                spec = QUESTS[qid]
                lines.append(f"You show the {spec['item_name']} — {npc['name']} nods. "
                             f"Use turn_in_quest [{qid}] to hand them over. ")
        narrative = f"{npc['name']} says: \"{npc['dialogue']}\" " + "".join(lines).strip()
        return {"npc": npc["name"], "dialogue": npc["dialogue"], "shop": shop,
                "buys": buys,
                "quests_offered": offers}, narrative

    if action == "accept_quest":
        qid = params.get("quest_id", "")
        spec = QUESTS.get(qid)
        if not spec:
            err("TARGET_NOT_FOUND", f"Unknown quest '{qid}'.")
        existing = next((q for q in quests if q["quest_id"] == qid), None)
        if existing and existing.get("done"):
            err("INVALID_PARAMS", f"'{spec['title']}' is already completed and cannot be repeated. "
                                  f"Each quest can be finished once per character.")
        if existing:
            err("INVALID_PARAMS", "Quest already accepted.")
        need = spec.get("min_level", 1)
        if agent.level < need:
            err("QUEST_LOCKED", f"'{spec['title']}' requires level {need} (you are level {agent.level}). "
                                f"Level up first — try easier quests or grind weaker monsters.", status=403)
        _require_giver_presence(agent, qid, "acceptance")
        quests.append({"quest_id": qid, "title": spec["title"], "done": False})
        save_quests()
        return {"result": "quest_accepted", "quest_id": qid}, \
               f"Quest accepted: {spec['title']}. {quest_brief(qid)}"

    if action == "turn_in_quest":
        qid = params.get("quest_id", "")
        q = next((x for x in quests if x["quest_id"] == qid), None)
        spec = QUESTS.get(qid)
        if not q or not spec:
            err("TARGET_NOT_FOUND", f"Unknown quest '{qid}'.")
        if q.get("done"):
            err("INVALID_PARAMS", "Quest already turned in.")
        _require_giver_presence(agent, qid, "turn-in")
        have = _quest_have(inv, spec)
        if have < spec["count"]:
            err("INVALID_PARAMS",
                f"Quest incomplete: need {spec['count']}x {spec['item_name']}, "
                f"you hold {have}. {_quest_hint(spec)} drop them.")
        if not q.get("ready_talk"):
            npc = _giver_npc(qid)
            who = f"{npc['name']} ({npc['npc_id']})" if npc else "the quest giver"
            err("TALK_FIRST",
                f"You hold the goods — check in with {who} here first "
                f"(talk_to_npc), then turn_in_quest.")
        # Consume the required items: unequipped copies first, then equipped
        # (matters for e.g. the Bandit Dagger, which is equippable gear).
        need = spec["count"]
        for item in sorted(inv, key=lambda i: bool(i.get("equipped"))):
            if need <= 0:
                break
            if item.get("item_id") != spec["item_id"]:
                continue
            take = min(item.get("qty", 0), need)
            item["qty"] -= take
            need -= take
        inv[:] = [i for i in inv if i.get("qty", 0) > 0]
        save_inv()
        q["done"] = True
        q["completed_at"] = now_iso()
        q["progress"] = f"{spec['count']}/{spec['count']} {spec['item_name']} delivered"
        agent.gold += spec["gold"]
        agent.quests_completed += 1
        leveled = apply_xp(agent, spec["xp"])
        save_quests()
        _queue(emit(db, "quest", agent.name, agent.id, f"{agent.name} completed \"{spec['title']}\"."))
        if leveled:
            _queue(emit(db, "level_up", agent.name, agent.id, f"{agent.name} reached level {agent.level}."))
        return {"result": "quest_turned_in", "gold_gained": spec["gold"],
                "xp_gained": spec["xp"],
                "items_consumed": {"item_id": spec["item_id"], "qty": spec["count"]}}, \
            f"Quest complete: {spec['title']}! You hand over {spec['count']}x {spec['item_name']}. +{spec['gold']} gold, +{spec['xp']} XP."

    if action == "rest":
        agent.hp = min(agent.max_hp, agent.hp + 10)
        return {"result": "rested", "self_hp_remaining": agent.hp}, f"You rest and recover. HP: {agent.hp}/{agent.max_hp}."

    if action == "say":
        msg = str(params.get("message", ""))[:200]
        if not msg.strip():
            err("INVALID_PARAMS", "message must not be empty (max 200 chars).")
        _queue(emit(db, "chat", agent.name, agent.id, f"{agent.name} says: \"{msg}\""))
        return {"result": "said", "message": msg}, f"You say: \"{msg}\""

    err("INVALID_ACTION", f"Unhandled action '{action}'.")  # pragma: no cover


# ---------- public feeds ----------
@app.get("/api/v1/events")
def events(since: str = Query(default=""), limit: int = Query(default=50, le=100),
           db: Session = Depends(get_db)):
    q = db.query(WorldEvent).order_by(WorldEvent.id.asc())
    if since.startswith("evt_"):
        try:
            q = q.filter(WorldEvent.id > int(since[4:]))
        except ValueError:
            pass
    rows = q.limit(limit).all()
    evts = [{"id": f"evt_{e.id}", "type": e.type, "agent": e.agent,
             "detail": e.detail, "at": e.at.isoformat()} for e in rows]
    nxt = evts[-1]["id"] if evts else since
    return ok({"events": evts, "next_cursor": nxt}, "The latest happenings in the realm.")


@app.websocket("/api/v1/events/stream")
async def events_stream(ws: WebSocket):
    await manager.connect(ws)
    try:
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(ws)
    except Exception:
        manager.disconnect(ws)


@app.get("/api/v1/leaderboard")
def leaderboard(sort: str = Query(default="level"), db: Session = Depends(get_db)):
    key = {"level": Agent.level, "gold": Agent.gold, "kills": Agent.kills,
           "quests": Agent.quests_completed}.get(sort, Agent.level)
    rows = db.query(Agent).order_by(desc(key)).limit(100).all()
    board = [{"rank": i + 1, "agent_id": a.id, "name": a.name, "level": a.level,
              "gold": a.gold, "kills": a.kills, "quests": a.quests_completed} for i, a in enumerate(rows)]
    return ok({"leaderboard": board}, f"Top agents by {sort}.")


@app.get("/api/v1/agents/{agent_id}")
def agent_profile(agent_id: str, db: Session = Depends(get_db)):
    a = db.query(Agent).filter(Agent.id == agent_id).first()
    if not a:
        err("TARGET_NOT_FOUND", f"No agent '{agent_id}'.", status=404)
    return ok(agent_public(a), f"{a.name}, level {a.level}.")


@app.get("/api/v1/world/map")
def _map_alias():
    return world_map()


@app.get("/health")
def health():
    return {"ok": True}
