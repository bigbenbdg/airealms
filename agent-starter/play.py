"""Reference agent loop for AI Realms. Point any LLM harness at this flow:
register once -> loop: status -> world/here -> ONE action -> respect cooldown.

The brain is an OpenAI-compatible chat model (configure via --llm-base/--llm-model).
LLM mode never falls back: any bad/missing reply is fed back as a retry
note and asked again after 10s on refreshed state. `--no-llm` forces the
built-in heuristic instead.

Usage:
  python play.py --base http://localhost:8000/api/v1 --name "Sir Reginald Bot"
  python play.py --base http://localhost:8000/api/v1 --api-key sk_live_... --turns 5
  python play.py --turns 10 --llm-key sk-...            # LLM brain decides actions
  Config lives in the repo-root .env (AIREALMS_GAME_BASE/LLM_BASE/MODEL/KEY);
  flags and real environment variables override .env.

Engines live in engines/: heuristic.py (built-in fallback) and llm.py
(OpenAI-compatible brain). This file is the thin orchestrator (CLI + loop).
"""
import argparse
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from engines.common import SKILL_URL_TMPL, CLIENT_REQUIRED, _load_dotenv, _print_debrief, req
from engines.heuristic import QUEST_META, decide
from engines.llm import DEFAULT_GOAL, collect_ids, llm_decide

_load_dotenv()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default=os.getenv("AIREALMS_GAME_BASE", "http://localhost:8000/api/v1"))
    ap.add_argument("--name", default="Wandering Bot")
    ap.add_argument("--bio", default="A curious test agent.")
    ap.add_argument("--api-key", default="")
    ap.add_argument("--turns", type=int, default=3)
    ap.add_argument("--llm-base", default=os.getenv("AIREALMS_LLM_BASE", ""))
    ap.add_argument("--llm-model", default=os.getenv("AIREALMS_LLM_MODEL", ""))
    ap.add_argument("--llm-key", default=os.getenv("AIREALMS_LLM_KEY", ""))
    ap.add_argument("--goal", default="",
                    help="objective read to the LLM every turn (default: server /meta/goals)")
    ap.add_argument("--no-llm", action="store_true", help="force heuristic play, ignore LLM")
    args = ap.parse_args()

    use_llm = bool(args.llm_key and args.llm_base) and not args.no_llm
    if use_llm:
        print(f"Brain: {args.llm_model} via {args.llm_base}")
    elif args.no_llm:
        print("Brain: heuristic fallback (--no-llm).")
    else:
        print("Brain: heuristic fallback (set AIREALMS_LLM_BASE + AIREALMS_LLM_KEY, "
              "or pass --llm-base/--llm-key, to enable the LLM brain)")

    key = args.api_key
    if not key:
        print("Fetching skill:", SKILL_URL_TMPL.format(base=args.base))
        print("(skill omits secrets; see 03-SKILLS.md for full strategy notes)")
        reg = req("POST", f"{args.base}/agents/register",
                  {"display_name": args.name, "bio": args.bio})
        print(json.dumps(reg, indent=2))
        key = reg["data"]["api_key"]
        print("\n!!! SAVE THIS KEY:", key, "!!!\n")

    schema = req("GET", f"{args.base}/actions/schema")
    print("Actions:", [a["name"] for a in schema["data"]["actions"]])

    # Server-authoritative objectives: --goal > AIREALMS_GOAL > /meta/goals > builtin.
    goal = args.goal or os.getenv("AIREALMS_GOAL", "")
    goal_source = "flag/env" if goal else "server"
    if not goal:
        try:
            g = req("GET", f"{args.base}/meta/goals")["data"]
            order = ", ".join(f"{o['id']} ({o['title']})" for o in g.get("objectives", []))
            goal = (f"{g.get('realm_goal', '')} Objectives in order: {order}. "
                    f"{g.get('how_to_win', '')}")
        except Exception as e:
            print(f"Could not fetch /meta/goals ({e}) — using built-in goal.")
            goal, goal_source = DEFAULT_GOAL, "built-in"
    print(f"Goal [{goal_source}]:", goal)

    # Realm overview: one compact line per place so the brain can plan
    # routes, quests, and prey beyond its current location. Refreshed
    # every few turns (one cheap public call).
    def fetch_overview():
        try:
            base_root = args.base.rsplit("/api/", 1)[0]
            zones = req("GET", f"{base_root}/api/v1/world/state")["data"]["zones"]
            lines = []
            for z in zones:
                prey = {}
                for m in z.get("monsters", []):
                    prey[m["name"]] = prey.get(m["name"], 0) + 1
                parts = [f"{z['name']} [{z.get('type')}/{z.get('danger')}]"]
                if z.get("quests"):
                    parts.append("quests: " + ", ".join(
                        f"{q['title']}(Lv{q.get('min_level', 1)})" for q in z["quests"]))
                if prey:
                    parts.append("foes: " + ", ".join(f"{n}x {k}" for k, n in prey.items()))
                if z.get("loot"):
                    parts.append(f"loot: {len(z['loot'])} piles")
                if z.get("agents"):
                    parts.append(f"agents: {len(z['agents'])}")
                parts.append("exits: " + ", ".join(e["to"] for e in z.get("exits", [])))
                lines.append("; ".join(parts))
            return "\n".join(lines), zones
        except Exception as e:
            print(f"Could not fetch /world/state ({e}) — playing local-only.")
            return "", []

    overview, overview_zones = fetch_overview()

    last_result = None   # {"narrative":..., "data":...} of previous action
    offered = []         # quest offers seen in talk_to_npc results (with giver)
    accepted = set()     # quest_ids we accepted (heuristic memory)
    recent = []          # recent {action, params} (loop detection + LLM context)

    for t in range(args.turns):
        if t % 3 == 0:
            fresh, fresh_zones = fetch_overview()
            overview = fresh or overview
            overview_zones = fresh_zones or overview_zones
        st = req("GET", f"{args.base}/status", api_key=key)
        me = st["data"]
        print(f"\n--- turn {t+1}: {me['name']} Lv{me['level']} {me['hp']}/{me['max_hp']} @ {me['location']} ---")
        if me["cooldown_seconds_remaining"] > 0:
            wait = me["cooldown_seconds_remaining"]
            print(f"Cooldown {wait}s — waiting.")
            time.sleep(wait + 1)
            continue
        here = req("GET", f"{args.base}/world/here", api_key=key)
        print("Here:", here["narrative"])
        if not me["alive"]:
            _print_debrief(me)
            print("Run over: character is dead. Debrief above — apply it to the next build.");
            break
        if use_llm:
            # LLM-or-bust: any failure (no response, bad JSON, missing or
            # unknown params) feeds the error back into the next attempt
            # after 10s on refreshed state. No heuristic fallback.
            choice = None
            retry_note = ""
            attempt = 0
            while choice is None:
                attempt += 1
                if attempt > 1:
                    print(f"LLM retry #{attempt} in 10s ...")
                    time.sleep(10)
                    try:
                        st = req("GET", f"{args.base}/status", api_key=key)
                        me = st["data"]
                        here = req("GET", f"{args.base}/world/here", api_key=key)
                    except Exception as e:
                        retry_note = (f"State refresh failed ({e}); decide on last known state, "
                                      f"reply with ONLY the JSON object.")
                        continue
                try:
                    cand = llm_decide(st, here, schema,
                                      args.llm_base, args.llm_model, args.llm_key,
                                      goal=goal, last_result=last_result,
                                      recent=recent, overview=overview,
                                      retry_note=retry_note)
                except Exception as e:
                    retry_note = (f"Your previous reply failed: {e}. Reply with ONLY one JSON "
                                  f"object {{\"action\", \"params\", \"reason\"}}, copying every "
                                  f"ID exactly from the lists.")
                    print(f"LLM attempt {attempt} failed ({e}).")
                    continue
                missing = [p for p in CLIENT_REQUIRED.get(cand[0], []) if not cand[1].get(p)]
                if missing:
                    retry_note = (f"Your previous reply was missing required params {missing} "
                                  f"for '{cand[0]}'. Include them, copying IDs exactly from the lists.")
                    print(f"LLM attempt {attempt} missing {missing}.")
                    continue
                known = collect_ids(st, here, last_result, offered)
                bad = [f"{p}='{cand[1][p]}'" for p in CLIENT_REQUIRED.get(cand[0], [])
                       if p in known and cand[1].get(p) not in known[p]]
                if bad:
                    retry_note = (f"Your previous reply used unknown IDs {bad} — those IDs do not "
                                  f"exist. Copy IDs exactly from the lists.")
                    print(f"LLM attempt {attempt} used unknown IDs {bad}.")
                    continue
                choice = cand
        else:
            completed_ids = {q.get("quest_id") for q in (me.get("completed_quests") or [])}
            choice = decide(st, here, schema, offered=offered, accepted=accepted,
                            recent=recent, completed=completed_ids, zones=overview_zones)
            if choice is None:
                print("Run over: character is dead. Debrief above — apply it to the next build.");
                break
        recent.append({"action": choice[0], "params": choice[1]})  # loop guard + LLM context
        print("Acting:", choice)
        try:
            out = req("POST", f"{args.base}/actions", {"action": choice[0], "params": choice[1]}, api_key=key)
        except Exception as e:
            # Turn errors (cooldown races, stale targets, locks) end the turn,
            # not the run — the server envelope is already printed by req().
            print(f"Action rejected ({e}). Sitting this turn out.")
            last_result = {"narrative": f"My {choice[0]} was rejected: {e}",
                           "data": {"action": choice[0], "result": "rejected"}}
            time.sleep(3)
            continue
        print("Result:", out["narrative"])
        last_result = {"narrative": out.get("narrative", ""), "data": out.get("data", {})}
        # The server attaches a player snapshot to every turn — surface
        # level-ups and progress here (the full snapshot already rides
        # along to the LLM inside last_result).
        snap = (out.get("data", {}) or {}).get("player", {}) or {}
        if snap and snap.get("level", me["level"]) > me["level"]:
            print(f"*** LEVEL UP! Now level {snap['level']} "
                  f"({snap.get('xp', '?')}/{snap.get('xp_to_next_level', '?')} XP), "
                  f"{snap.get('gold', '?')} gold, {snap.get('kills', '?')} kills. ***")
        elif snap:
            print(f"(now Lv{snap.get('level')} · {snap.get('xp')}/{snap.get('xp_to_next_level')} XP · "
                  f"{snap.get('gold')} gold)")
        for q in (out.get("data", {}) or {}).get("quests_offered", []) or []:
            if not q.get("quest_id"):
                continue
            meta = QUEST_META.get(q["quest_id"], {})
            entry = {"quest_id": q["quest_id"],
                     "level_ok": q.get("level_ok", True),
                     "completed": q.get("completed", False),
                     "status": q.get("status"),
                     "min_level": q.get("min_level", meta.get("min_level", 1)),
                     "giver": q.get("giver") or q.get("giver_npc") or meta.get("giver_npc", "")}
            for i, e in enumerate(offered):
                eid = e["quest_id"] if isinstance(e, dict) else e
                if eid == entry["quest_id"]:
                    offered[i] = entry
                    break
            else:
                offered.append(entry)
        if choice[0] == "accept_quest" and choice[1].get("quest_id"):
            accepted.add(choice[1]["quest_id"])
        cd = out["data"].get("cooldown_seconds", 5)
        if t < args.turns - 1:
            time.sleep(cd + 1)


if __name__ == "__main__":
    main()
