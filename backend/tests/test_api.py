"""Smoke tests for the v1 API (02-api-spec.md). Run: pytest -q"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import app.main as main_module
from app.main import app
from app.db import Base, engine, SessionLocal
from fastapi.testclient import TestClient


def fresh_client():
    from app.engine import _hits, _seen_keys
    _hits.clear()
    _seen_keys.clear()
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    from app.seed import seed_monsters
    seed_monsters(db)
    db.close()
    return TestClient(app)


def register(client, name="Tester"):
    r = client.post("/api/v1/agents/register", json={"display_name": name, "bio": "test"})
    assert r.status_code == 200, r.text
    return r.json()["data"]


def test_register_status_here_schema():
    c = fresh_client()
    reg = register(c)
    h = {"Authorization": f"Bearer {reg['api_key']}"}
    s = c.get("/api/v1/status", headers=h)
    assert s.status_code == 200 and s.json()["data"]["location"] == "riverside_village"
    w = c.get("/api/v1/world/here", headers=h)
    assert "exits" in w.json()["data"]
    sch = c.get("/api/v1/actions/schema")
    assert any(a["name"] == "attack" for a in sch.json()["data"]["actions"])
    m = c.get("/api/v1/world/map")
    assert len(m.json()["data"]["locations"]) == 6


def test_move_and_cooldown_and_idempotency():
    c = fresh_client()
    reg = register(c)
    h = {"Authorization": f"Bearer {reg['api_key']}"}
    r1 = c.post("/api/v1/actions", json={"action": "move", "params": {"to": "oakhollow_forest"}}, headers=h)
    assert r1.status_code == 200, r1.text
    r2 = c.post("/api/v1/actions", json={"action": "move", "params": {"to": "riverside_village"}}, headers=h)
    assert r2.status_code == 429  # COOLDOWN_ACTIVE
    assert r2.json()["detail"]["error"]["code"] == "COOLDOWN_ACTIVE"
    # idempotent replay returns cached success even under a new cooldown:
    # reset cooldown, do a keyed action, then replay the same key while cooling down
    from app.models import Agent as _A
    from datetime import datetime as _dt, timezone as _tz
    _db = SessionLocal()
    _a = _db.query(_A).filter(_A.id == reg["agent_id"]).first()
    _a.cooldown_until = _dt(1970, 1, 1, tzinfo=_tz.utc)
    _db.commit(); _db.close()
    r3 = c.post("/api/v1/actions", json={"action": "say", "params": {"message": "hello"}},
                headers={**h, "Idempotency-Key": "k1"})
    assert r3.status_code == 200
    r4 = c.post("/api/v1/actions", json={"action": "attack", "params": {"target_id": "x"}},
                headers={**h, "Idempotency-Key": "k1"})
    assert r4.status_code == 200 and r4.json()["data"]["action"] == "say"


def test_attack_quest_talk_say_events_leaderboard_profile():
    c = fresh_client()
    reg = register(c, "Slayer")
    h = {"Authorization": f"Bearer {reg['api_key']}"}
    # teleport-adjacent: move to forest (move has 10s cooldown; single action ok)
    assert c.post("/api/v1/actions", json={"action": "move", "params": {"to": "oakhollow_forest"}}, headers=h).status_code == 200
    # force cooldown expiry for test speed
    from app.models import Agent
    db = SessionLocal()
    from datetime import datetime, timezone
    a = db.query(Agent).filter(Agent.id == reg["agent_id"]).first()
    a.cooldown_until = datetime(1970, 1, 1, tzinfo=timezone.utc)
    db.commit(); db.close()
    here = c.get("/api/v1/world/here", headers=h).json()["data"]
    assert here["monsters"], "seed should place monsters in forest"
    mid = here["monsters"][0]["monster_id"]
    atk = c.post("/api/v1/actions", json={"action": "attack", "params": {"target_id": mid}}, headers=h)
    assert atk.status_code == 200 and atk.json()["data"]["action"] == "attack"
    ev = c.get("/api/v1/events?limit=10")
    assert ev.json()["data"]["events"], "actions should emit events"
    lb = c.get("/api/v1/leaderboard?sort=level")
    assert any(r["agent_id"] == reg["agent_id"] for r in lb.json()["data"]["leaderboard"])
    prof = c.get(f"/api/v1/agents/{reg['agent_id']}")
    assert prof.json()["data"]["name"] == "Slayer"
    assert "api_key" not in prof.text  # public profile must not leak secrets


def test_invalid_action_and_auth():
    c = fresh_client()
    r = c.get("/api/v1/status", headers={"Authorization": "Bearer nope"})
    assert r.status_code == 401
    reg = register(c)
    h = {"Authorization": f"Bearer {reg['api_key']}"}
    bad = c.post("/api/v1/actions", json={"action": "fly", "params": {}}, headers=h)
    assert bad.json()["detail"]["error"]["code"] == "INVALID_ACTION"


def test_meta_goals():
    c = fresh_client()
    g = c.get("/api/v1/meta/goals")
    assert g.status_code == 200, g.text
    d = g.json()["data"]
    assert d["realm_goal"] and len(d["objectives"]) == 5
    assert [o["id"] for o in d["objectives"]][0] == "survive"
    assert d["starter_path"] and d["death_policy"] and d["how_to_win"]


def test_death_report_and_agent_dead_hint():
    from datetime import datetime, timezone
    from app.models import Agent as _A, WorldEvent as _E
    c = fresh_client()
    reg = register(c, "Doomed")
    h = {"Authorization": f"Bearer {reg['api_key']}"}
    alive = c.get("/api/v1/status", headers=h).json()["data"]
    assert alive["alive"] is True and alive["death_report"] is None
    db = SessionLocal()
    a = db.query(_A).filter(_A.id == reg["agent_id"]).first()
    a.alive = False
    a.hp = 0
    db.add(_E(type="death", agent=a.name, agent_id=a.id,
              detail=f"{a.name} was slain by a Cave Troll.",
              at=datetime.now(timezone.utc)))
    db.commit()
    db.close()
    st = c.get("/api/v1/status", headers=h).json()["data"]
    assert st["alive"] is False
    rep = st["death_report"]
    assert "Cave Troll" in rep["killed_by"] and len(rep["lessons"]) >= 3
    assert "slain by" in st["death_report"]["detail"]
    act = c.post("/api/v1/actions", json={"action": "rest", "params": {}}, headers=h)
    body = act.json()["detail"]
    assert body["error"]["code"] == "AGENT_DEAD" and "Cave Troll" in body["error"]["message"]


def _set_hp_and_ready(agent_id, hp):
    from datetime import datetime, timezone
    from app.models import Agent as _A
    from app.engine import _hits
    _hits.clear()  # reset the 5-burst rate limiter between test steps
    db = SessionLocal()
    a = db.query(_A).filter(_A.id == agent_id).first()
    a.hp = hp
    a.cooldown_until = datetime(1970, 1, 1, tzinfo=timezone.utc)
    db.commit()
    db.close()


def test_village_regen():
    c = fresh_client()
    reg = register(c, "Villager")
    h = {"Authorization": f"Bearer {reg['api_key']}"}
    # hurt in town -> next action regenerates +5
    _set_hp_and_ready(reg["agent_id"], 10)
    r = c.post("/api/v1/actions", json={"action": "talk_to_npc", "params": {"npc_id": "npc_blacksmith"}}, headers=h)
    assert r.status_code == 200, r.text
    assert r.json()["data"]["hp_regen"] == 5
    assert c.get("/api/v1/status", headers=h).json()["data"]["hp"] == 15
    # no regen in the wild: move to forest, hurt, act -> hp unchanged
    _set_hp_and_ready(reg["agent_id"], 10)
    assert c.post("/api/v1/actions", json={"action": "move", "params": {"to": "oakhollow_forest"}}, headers=h).status_code == 200
    here = c.get("/api/v1/world/here", headers=h).json()
    assert "Safe ground" not in here["narrative"]
    # move regenerated on arrival in... forest is wild, so arrival healed nothing; re-hurt then say
    _set_hp_and_ready(reg["agent_id"], 10)
    s = c.post("/api/v1/actions", json={"action": "say", "params": {"message": "hello wilds"}}, headers=h)
    assert s.status_code == 200, s.text
    assert "hp_regen" not in s.json()["data"]
    assert c.get("/api/v1/status", headers=h).json()["data"]["hp"] == 10
    # town hint is advertised in village narrative
    _set_hp_and_ready(reg["agent_id"], 10)
    assert c.post("/api/v1/actions", json={"action": "move", "params": {"to": "riverside_village"}}, headers=h).status_code == 200
    town = c.get("/api/v1/world/here", headers=h).json()
    assert "Safe ground" in town["narrative"] and "+5 HP" in town["narrative"]


def test_quest_brief_names_item_and_location():
    c = fresh_client()
    reg = register(c, "Questor")
    h = {"Authorization": f"Bearer {reg['api_key']}"}
    talk = c.post("/api/v1/actions", json={"action": "talk_to_npc", "params": {"npc_id": "npc_blacksmith"}}, headers=h)
    assert talk.status_code == 200, talk.text
    body = talk.json()
    assert "Rat Pelt" in body["narrative"] and "Oakhollow Forest" in body["narrative"]
    assert "q_ratcatcher" in body["narrative"]
    offered = body["data"]["quests_offered"][0]
    assert offered["item_id"] == "itm_rat_pelt" and offered["item_name"] == "Rat Pelt"
    assert offered["count"] == 3
    assert "target" not in offered
    _set_hp_and_ready(reg["agent_id"], 25)
    acc = c.post("/api/v1/actions", json={"action": "accept_quest", "params": {"quest_id": "q_ratcatcher"}}, headers=h)
    assert acc.status_code == 200, acc.text
    assert "Rat Pelt" in acc.json()["narrative"] and "Oakhollow Forest" in acc.json()["narrative"]
    st = c.get("/api/v1/status", headers=h).json()["data"]
    assert "Rat Pelt" in st["active_quests"][0]["progress"]


def test_monster_drop_shown_on_kill_and_in_here():
    c = fresh_client()
    reg = register(c, "Looter")
    h = {"Authorization": f"Bearer {reg['api_key']}"}
    assert c.post("/api/v1/actions", json={"action": "move", "params": {"to": "oakhollow_forest"}}, headers=h).status_code == 200
    here = c.get("/api/v1/world/here", headers=h).json()["data"]
    rat = next(m for m in here["monsters"] if m["name"] == "Giant Rat")
    assert rat["drops"] and rat["drops"]["name"] == "Rat Pelt"
    mid = rat["monster_id"]
    out = None
    for _ in range(5):  # rats have 8 HP; guaranteed Rat Pelt on kill
        _set_hp_and_ready(reg["agent_id"], 25)
        r = c.post("/api/v1/actions", json={"action": "attack", "params": {"target_id": mid}}, headers=h)
        assert r.status_code == 200, r.text
        out = r.json()
        if out["data"]["result"] == "kill":
            break
    assert out["data"]["result"] == "kill", "rat should die within 5 hits"
    assert "Rat Pelt" in out["narrative"]
    assert "auto-looted" in out["narrative"] and "no pick_up" in out["narrative"]
    items = out["data"]["loot"]["items"]
    assert items and items[0]["item_id"] == "itm_rat_pelt"
    inv = c.get("/api/v1/status", headers=h).json()["data"]["inventory"]
    assert any(i["item_id"] == "itm_rat_pelt" for i in inv)
    evts = c.get("/api/v1/events?limit=10").json()["data"]["events"]
    assert any("Rat Pelt" in e["detail"] for e in evts), "drop should appear in the event feed"
    # auto-loot must not leave a ground pile behind: no GroundItem row for the drop
    db = SessionLocal()
    from app.models import GroundItem
    assert db.query(GroundItem).filter(
        GroundItem.location == "oakhollow_forest",
        GroundItem.item_id == "itm_rat_pelt").count() == 0
    db.close()
    # second rat kill stacks the same inventory entry instead of duplicating it
    here2 = c.get("/api/v1/world/here", headers=h).json()["data"]
    rat2 = next(m for m in here2["monsters"] if m["name"] == "Giant Rat")
    out2 = None
    for _ in range(5):
        _set_hp_and_ready(reg["agent_id"], 25)
        r = c.post("/api/v1/actions", json={"action": "attack", "params": {"target_id": rat2["monster_id"]}}, headers=h)
        assert r.status_code == 200, r.text
        out2 = r.json()
        if out2["data"]["result"] == "kill":
            break
    assert out2["data"]["result"] == "kill"
    inv2 = c.get("/api/v1/status", headers=h).json()["data"]["inventory"]
    pelts = [i for i in inv2 if i["item_id"] == "itm_rat_pelt"]
    assert len(pelts) == 1 and pelts[0].get("qty", 0) == 2


def test_world_state_pick_up_and_public_hp():
    c = fresh_client()
    reg = register(c, "Scout")
    h = {"Authorization": f"Bearer {reg['api_key']}"}
    st = c.get("/api/v1/world/state")
    assert st.status_code == 200, st.text
    zones = st.json()["data"]["zones"]
    assert len(zones) == 6
    village = next(z for z in zones if z["id"] == "riverside_village")
    assert any(a["agent_id"] == reg["agent_id"] and a["hp"] == 25 for a in village["agents"])
    assert any(i["item_id"] == "itm_healing_potion" for i in village["loot"])
    forest = next(z for z in zones if z["id"] == "oakhollow_forest")
    assert any(m["name"] == "Giant Rat" and m["hp"] == 8 for m in forest["monsters"])
    # public profile exposes HP for scouting/RTS bars
    prof = c.get(f"/api/v1/agents/{reg['agent_id']}").json()["data"]
    assert prof["hp"] == 25 and prof["max_hp"] == 25
    # pick up the village potion
    r = c.post("/api/v1/actions", json={"action": "pick_up", "params": {"item_id": "itm_healing_potion"}}, headers=h)
    assert r.status_code == 200, r.text
    assert r.json()["data"]["result"] == "picked_up"
    inv = c.get("/api/v1/status", headers=h).json()["data"]["inventory"]
    assert sum(i.get("qty", 0) for i in inv if i["item_id"] == "itm_healing_potion") == 2
    zones2 = c.get("/api/v1/world/state").json()["data"]["zones"]
    village2 = next(z for z in zones2 if z["id"] == "riverside_village")
    assert not any(i["item_id"] == "itm_healing_potion" for i in village2["loot"])
    # picking up what isn't there errors cleanly
    _set_hp_and_ready(reg["agent_id"], 25)
    bad = c.post("/api/v1/actions", json={"action": "pick_up", "params": {"item_id": "itm_healing_potion"}}, headers=h)
    assert bad.json()["detail"]["error"]["code"] == "TARGET_NOT_FOUND"


def test_respawn_delay_scales_with_size():
    from app.engine import respawn_delay_seconds, respawn_due
    from app.models import Monster
    c = fresh_client()
    db = SessionLocal()
    rats = db.query(Monster).filter(Monster.name == "Giant Rat").all()
    drake = db.query(Monster).filter(Monster.name == "Ember Drake").first()
    assert respawn_delay_seconds(rats[0]) < respawn_delay_seconds(drake)
    assert respawn_delay_seconds(rats[0]) == 45 + 8 * 5  # 85s for 8 HP
    # freshly-killed rat stays dead; long-dead rat revives on read
    from datetime import datetime, timezone, timedelta
    rats[0].alive = False
    rats[0].died_at = datetime.now(timezone.utc)
    rats[1].alive = False
    rats[1].died_at = datetime.now(timezone.utc) - timedelta(seconds=3600)
    db.commit()
    assert respawn_due(db) == 1
    db.refresh(rats[0])
    db.refresh(rats[1])
    assert rats[0].alive is False and rats[1].alive is True
    assert rats[1].hp == rats[1].max_hp and rats[1].died_at is None
    db.close()


def test_kill_sets_died_at_and_here_revives():
    from datetime import datetime, timezone, timedelta
    from app.models import Monster
    c = fresh_client()
    reg = register(c, "Hunter")
    h = {"Authorization": f"Bearer {reg['api_key']}"}
    assert c.post("/api/v1/actions", json={"action": "move", "params": {"to": "oakhollow_forest"}}, headers=h).status_code == 200
    mid = next(m["monster_id"] for m in
               c.get("/api/v1/world/here", headers=h).json()["data"]["monsters"]
               if m["name"] == "Giant Rat")
    for _ in range(5):
        _set_hp_and_ready(reg["agent_id"], 25)
        out = c.post("/api/v1/actions", json={"action": "attack", "params": {"target_id": mid}}, headers=h).json()
        if out["data"]["result"] == "kill":
            break
    assert out["data"]["result"] == "kill"
    db = SessionLocal()
    m = db.query(Monster).filter(Monster.id == mid).first()
    assert m.alive is False and m.died_at is not None
    # still dead on immediate re-read ...
    _set_hp_and_ready(reg["agent_id"], 25)
    assert mid not in [x["monster_id"] for x in
                       c.get("/api/v1/world/here", headers=h).json()["data"]["monsters"]]
    # ... but an old corpse revives when the zone is read
    m.died_at = datetime.now(timezone.utc) - timedelta(seconds=3600)
    db.commit()
    db.close()
    _set_hp_and_ready(reg["agent_id"], 25)
    seen = c.get("/api/v1/world/here", headers=h).json()["data"]["monsters"]
    assert any(x["monster_id"] == mid and x["hp"] == x["max_hp"] for x in seen)


def test_max_monsters_per_location_and_backfill():
    from app.models import Monster
    from app.seed import seed_monsters, MAX_MONSTERS_PER_LOCATION, MONSTER_SPAWNS
    assert MAX_MONSTERS_PER_LOCATION == 10
    c = fresh_client()
    db = SessionLocal()
    counts = {}
    for m in db.query(Monster).all():
        counts[m.location] = counts.get(m.location, 0) + 1
    assert counts["oakhollow_forest"] == 6  # 3 rats + 3 wolves
    assert counts["deep_cave"] == 4
    assert all(n <= 10 for n in counts.values())
    assert len(MONSTER_SPAWNS) == db.query(Monster).count()
    # backfill: a legacy DB missing a spawn row gains it on reseed
    db.query(Monster).filter(Monster.id == "mon_wolf_3").delete()
    db.commit()
    seed_monsters(db)
    assert db.query(Monster).filter(Monster.id == "mon_wolf_3").count() == 1
    # cap enforced: extra spawns for a full zone are skipped
    db.query(Monster).filter(Monster.location == "oakhollow_forest").delete()
    for i in range(10):
        db.add(Monster(id=f"mon_tmp_{i}", name="Giant Rat", location="oakhollow_forest",
                       hp=8, max_hp=8, alive=True))
    db.commit()
    seed_monsters(db)
    assert db.query(Monster).filter(Monster.location == "oakhollow_forest").count() == 10
    db.close()


def _set_level(agent_id, level):
    db = SessionLocal()
    from app.models import Agent as _A
    a = db.query(_A).filter(_A.id == agent_id).first()
    a.level = level
    db.commit()
    db.close()
    from app.engine import _hits
    _hits.clear()


def test_quest_min_level_gate_and_chain():
    c = fresh_client()
    reg = register(c, "Climber")
    h = {"Authorization": f"Bearer {reg['api_key']}"}
    # locked at level 1: names the required level
    r = c.post("/api/v1/actions", json={"action": "accept_quest", "params": {"quest_id": "q_drakescale"}}, headers=h)
    body = r.json()["detail"]
    assert body["error"]["code"] == "QUEST_LOCKED" and "level 5" in body["error"]["message"]
    _set_level(reg["agent_id"], 2)
    r2 = c.post("/api/v1/actions", json={"action": "accept_quest", "params": {"quest_id": "q_drakescale"}}, headers=h)
    assert r2.json()["detail"]["error"]["code"] == "QUEST_LOCKED"
    # unlocked quest accepts and brief states requirement + target
    # (accept is in person: talk to the giver here first)
    _set_hp_and_ready(reg["agent_id"], 25)
    assert c.post("/api/v1/actions", json={"action": "talk_to_npc", "params": {"npc_id": "npc_blacksmith"}}, headers=h).status_code == 200
    _set_hp_and_ready(reg["agent_id"], 25)
    ok = c.post("/api/v1/actions", json={"action": "accept_quest", "params": {"quest_id": "q_ratcatcher"}}, headers=h)
    assert ok.status_code == 200, ok.text
    assert "Requires level 1" in ok.json()["narrative"] and "Giant Rat" in ok.json()["narrative"]
    # talk flags level_ok per offer (ratcatcher ok, nothing locked for this NPC at L2... use warden via state)
    _set_hp_and_ready(reg["agent_id"], 25)
    talk = c.post("/api/v1/actions", json={"action": "talk_to_npc", "params": {"npc_id": "npc_blacksmith"}}, headers=h)
    offered = {q["quest_id"]: q for q in talk.json()["data"]["quests_offered"]}
    assert offered["q_ratcatcher"]["level_ok"] is True
    assert offered["q_ratcatcher"]["min_level"] == 1
    # chain prizes: full clear pays ~1200 quest XP
    from app.seed import QUESTS
    total = sum(q["xp"] for q in QUESTS.values())
    assert total >= 1200, f"quest XP total {total} too low to power leveling"
    assert {q for q in QUESTS} >= {"q_ratcatcher", "q_wolfpack", "q_bandit_toll", "q_trollbane", "q_marshlight", "q_drakescale"}


def test_world_state_full_place_intel():
    c = fresh_client()
    zones = c.get("/api/v1/world/state").json()["data"]["zones"]
    by_id = {z["id"]: z for z in zones}
    # every place exposes everything a player needs to decide
    for z in zones:
        for key in ("danger", "exits", "agents", "monsters", "loot", "npcs", "quests", "description"):
            assert key in z, f"{z['id']} missing {key}"
    assert by_id["oakhollow_forest"]["danger"] == "mild"
    assert by_id["deep_cave"]["danger"] == "deadly"
    assert by_id["riverside_village"]["danger"] == "safe"
    assert {e["to"] for e in by_id["riverside_village"]["exits"]} == {"oakhollow_forest", "capital_city"}
    toran = next(n for n in by_id["riverside_village"]["npcs"] if n["npc_id"] == "npc_blacksmith")
    assert toran["has_quest"] is True and toran["can_trade"] is False
    # commerce is exclusive to Armorer Sella in the home village
    sella = next(n for n in by_id["riverside_village"]["npcs"] if n["npc_id"] == "npc_armorer_sella")
    assert sella["can_trade"] is True and sella["has_quest"] is False
    rq = next(q for q in by_id["riverside_village"]["quests"] if q["quest_id"] == "q_ratcatcher")
    assert rq["item_id"] == "itm_rat_pelt" and rq["item_name"] == "Rat Pelt" and rq["min_level"] == 1
    assert rq["repeatable"] is False
    assert "Rat Pelt" in rq["brief"] and "Giant Rat" in rq["brief"]
    assert "target" not in rq
    assert rq["giver"] == "Old Toran"
    # warden's end-game quest is visible with its gate from anywhere
    dq = next(q for q in by_id["ember_ridge"]["quests"] if q["quest_id"] == "q_drakescale")
    assert dq["min_level"] == 5 and dq["xp"] == 400


def test_missing_params_rejected_up_front():
    c = fresh_client()
    reg = register(c, "Clumsy")
    h = {"Authorization": f"Bearer {reg['api_key']}"}
    for action, params in [("attack", {}), ("move", {}), ("scout", {}), ("say", {}),
                           ("talk_to_npc", {}), ("accept_quest", {"quest_id": ""})]:
        from app.engine import _hits
        _hits.clear()
        r = c.post("/api/v1/actions", json={"action": action, "params": params}, headers=h)
        body = r.json()["detail"]
        assert body["error"]["code"] == "INVALID_PARAMS", f"{action} {params}: {body}"
        assert "required param" in body["error"]["message"]


def test_scout_reveals_neighbor_without_moving():
    c = fresh_client()
    reg = register(c, "Lookout")
    h = {"Authorization": f"Bearer {reg['api_key']}"}
    r = c.post("/api/v1/actions", json={"action": "scout", "params": {"to": "oakhollow_forest"}}, headers=h)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["data"]["result"] == "scouted"
    intel = body["data"]["intel"]
    assert intel["id"] == "oakhollow_forest" and intel["danger"] == "mild"
    assert any(m["name"] == "Giant Rat" for m in intel["monsters"])
    assert any(q["quest_id"] == "q_wolfpack" for q in intel["quests"])
    assert "Oakhollow Forest" in body["narrative"] and "Giant Rat" in body["narrative"]
    # still home: scouting doesn't move
    assert c.get("/api/v1/status", headers=h).json()["data"]["location"] == "riverside_village"
    # non-adjacent target rejected
    _set_hp_and_ready(reg["agent_id"], 25)
    bad = c.post("/api/v1/actions", json={"action": "scout", "params": {"to": "ember_ridge"}}, headers=h)
    assert bad.json()["detail"]["error"]["code"] == "INVALID_PARAMS"


def _give_quest_items(agent_id, item_id, qty, name=None):
    """Add qty of item_id to the agent's inventory (quest-item test setup)."""
    import json as _json
    from app.models import Agent as _A
    db = SessionLocal()
    a = db.query(_A).filter(_A.id == agent_id).first()
    inv = _json.loads(a.inventory)
    have = next((i for i in inv if i["item_id"] == item_id), None)
    if have:
        have["qty"] = have.get("qty", 0) + qty
    else:
        inv.append({"item_id": item_id, "name": name or item_id,
                    "qty": qty, "equipped": False})
    a.inventory = _json.dumps(inv)
    db.commit()
    db.close()


def test_completed_quest_flagged_and_not_repeatable():
    c = fresh_client()
    reg = register(c, "Finisher")
    h = {"Authorization": f"Bearer {reg['api_key']}"}
    # accept is in person: talk to Old Toran at Riverside first
    _talk(c, h, reg["agent_id"], "npc_blacksmith")
    _set_hp_and_ready(reg["agent_id"], 25)
    assert c.post("/api/v1/actions", json={"action": "accept_quest", "params": {"quest_id": "q_ratcatcher"}}, headers=h).status_code == 200
    _give_quest_items(reg["agent_id"], "itm_rat_pelt", 3, "Rat Pelt")
    # turn-in is in person after a check-in talk while holding the items
    _talk(c, h, reg["agent_id"], "npc_blacksmith")
    _set_hp_and_ready(reg["agent_id"], 25)
    done = c.post("/api/v1/actions", json={"action": "turn_in_quest", "params": {"quest_id": "q_ratcatcher"}}, headers=h)
    assert done.status_code == 200, done.text
    assert done.json()["data"]["result"] == "quest_turned_in"
    assert done.json()["data"]["items_consumed"] == {"item_id": "itm_rat_pelt", "qty": 3}
    # turn-in consumes the items
    st = c.get("/api/v1/status", headers=h).json()["data"]
    assert not any(i["item_id"] == "itm_rat_pelt" for i in st["inventory"])
    # completion is flagged on the player
    st = c.get("/api/v1/status", headers=h).json()["data"]
    assert st["active_quests"] == []
    assert len(st["completed_quests"]) == 1
    assert st["completed_quests"][0]["quest_id"] == "q_ratcatcher"
    assert st["completed_quests"][0]["completed_at"]
    # re-accept is refused as completed, not merely "accepted"
    _set_hp_and_ready(reg["agent_id"], 25)
    again = c.post("/api/v1/actions", json={"action": "accept_quest", "params": {"quest_id": "q_ratcatcher"}}, headers=h)
    body = again.json()["detail"]
    assert body["error"]["code"] == "INVALID_PARAMS" and "already completed" in body["error"]["message"]
    # re-turn-in is refused too
    _set_hp_and_ready(reg["agent_id"], 25)
    again2 = c.post("/api/v1/actions", json={"action": "turn_in_quest", "params": {"quest_id": "q_ratcatcher"}}, headers=h)
    assert "already turned in" in again2.json()["detail"]["error"]["message"]
    # offers advertise the completed flag so brains don't waste the turn
    _set_hp_and_ready(reg["agent_id"], 25)
    talk = c.post("/api/v1/actions", json={"action": "talk_to_npc", "params": {"npc_id": "npc_blacksmith"}}, headers=h)
    offered = {q["quest_id"]: q for q in talk.json()["data"]["quests_offered"]}
    assert offered["q_ratcatcher"]["completed"] is True


def test_every_action_returns_player_snapshot():
    c = fresh_client()
    reg = register(c, "Observed")
    h = {"Authorization": f"Bearer {reg['api_key']}"}
    r = c.post("/api/v1/actions", json={"action": "say", "params": {"message": "hi"}}, headers=h)
    assert r.status_code == 200, r.text
    p = r.json()["data"]["player"]
    for key in ("level", "xp", "xp_to_next_level", "hp", "max_hp", "gold",
                "kills", "quests_completed", "location", "alive", "inventory",
                "equipped",
                "cooldown_seconds_remaining"):
        assert key in p, f"player snapshot missing {key}"
    assert r.json()["data"]["active_quests"] == []
    assert p["level"] == 1 and p["location"] == "riverside_village" and p["alive"] is True
    # snapshot carries the full inventory (potions et al) + equipped slots
    assert any(i["item_id"] == "itm_healing_potion" for i in p["inventory"])
    assert p["equipped"]["weapon"]["item_id"] == "itm_rusty_sword"
    assert p["equipped"]["armor"] is None
    # snapshot tracks progress: kill XP shows up inline without /status
    _set_hp_and_ready(reg["agent_id"], 25)
    assert c.post("/api/v1/actions", json={"action": "move", "params": {"to": "oakhollow_forest"}}, headers=h).status_code == 200
    _set_hp_and_ready(reg["agent_id"], 25)
    mid = c.get("/api/v1/world/here", headers=h).json()["data"]["monsters"][0]["monster_id"]
    atk = c.post("/api/v1/actions", json={"action": "attack", "params": {"target_id": mid}}, headers=h).json()["data"]
    assert atk["player"]["xp"] == atk["xp_gained"] or atk["player"]["level"] > 1
    assert atk["player"]["location"] == "oakhollow_forest"
    # snapshot tracks gear inline: buy + equip shows up without /status
    _move(c, h, reg["agent_id"], "riverside_village")
    _talk(c, h, reg["agent_id"], "npc_armorer_sella")
    _set_gold(reg["agent_id"], 1000)
    bought = _buy(c, h, reg["agent_id"], "npc_armorer_sella", "itm_chainmail")
    # chainmail needs level 3...
    assert bought.json()["detail"]["error"]["code"] == "QUEST_LOCKED"
    bought2 = _buy(c, h, reg["agent_id"], "npc_armorer_sella", "itm_cloth_garb")
    assert bought2.status_code == 200, bought2.text
    assert any(i["item_id"] == "itm_cloth_garb" for i in bought2.json()["data"]["player"]["inventory"])
    _set_hp_and_ready(reg["agent_id"], 25)
    eq = c.post("/api/v1/actions", json={"action": "equip_item",
                "params": {"item_id": "itm_cloth_garb"}}, headers=h).json()["data"]
    assert eq["player"]["equipped"]["armor"]["item_id"] == "itm_cloth_garb"
    assert eq["player"]["equipped"]["weapon"]["item_id"] == "itm_rusty_sword"
    # ...and selling it drops it from the snapshot
    sold = _sell(c, h, reg["agent_id"], "npc_armorer_sella", "itm_cloth_garb")
    assert sold.status_code == 200, sold.text
    assert not any(i["item_id"] == "itm_cloth_garb" for i in sold.json()["data"]["player"]["inventory"])
    assert sold.json()["data"]["player"]["equipped"]["armor"] is None


def _talk(c, h, agent_id, npc):
    _set_hp_and_ready(agent_id, 25)
    r = c.post("/api/v1/actions", json={"action": "talk_to_npc", "params": {"npc_id": npc}}, headers=h)
    assert r.status_code == 200, r.text
    return r.json()


def test_npc_notices_quest_state_and_suggests_other_work():
    c = fresh_client()
    reg = register(c, "Networker")
    h = {"Authorization": f"Bearer {reg['api_key']}"}
    # fresh: quest pitched as available with full brief
    t1 = _talk(c, h, reg["agent_id"], "npc_blacksmith")
    assert "Bring 3x Rat Pelt" in t1["narrative"]
    assert t1["data"]["quests_offered"][0]["status"] == "available"
    # one-time nature is explicit: narrative pitch + repeatable flag
    assert "One-time" in t1["narrative"]
    assert t1["data"]["quests_offered"][0]["repeatable"] is False
    # accepted: NPC notices progress and hints where the drops come from
    _set_hp_and_ready(reg["agent_id"], 25)
    assert c.post("/api/v1/actions", json={"action": "accept_quest", "params": {"quest_id": "q_ratcatcher"}}, headers=h).status_code == 200
    t2 = _talk(c, h, reg["agent_id"], "npc_blacksmith")
    assert "How goes" in t2["narrative"] and "Oakhollow Forest" in t2["narrative"]
    assert "Rat Pelt" in t2["narrative"]
    assert t2["data"]["quests_offered"][0]["status"] == "in_progress"
    # completed: check in with the goods, then hand them over
    _give_quest_items(reg["agent_id"], "itm_rat_pelt", 3, "Rat Pelt")
    t_check = _talk(c, h, reg["agent_id"], "npc_blacksmith")
    assert "turn_in_quest" in t_check["narrative"]
    _set_hp_and_ready(reg["agent_id"], 25)
    assert c.post("/api/v1/actions", json={"action": "turn_in_quest", "params": {"quest_id": "q_ratcatcher"}}, headers=h).status_code == 200
    t3 = _talk(c, h, reg["agent_id"], "npc_blacksmith")
    assert "fine work" in t3["narrative"]
    assert t3["data"]["quests_offered"][0]["status"] == "completed"
    assert "For more work" in t3["narrative"] and "Scout Liora" in t3["narrative"]


def test_turn_in_without_items_fails_and_names_need():
    c = fresh_client()
    reg = register(c, "EmptyHanded")
    h = {"Authorization": f"Bearer {reg['api_key']}"}
    _talk(c, h, reg["agent_id"], "npc_blacksmith")
    _set_hp_and_ready(reg["agent_id"], 25)
    assert c.post("/api/v1/actions", json={"action": "accept_quest", "params": {"quest_id": "q_ratcatcher"}}, headers=h).status_code == 200
    _set_hp_and_ready(reg["agent_id"], 25)
    # no pelts held: turn-in refused, naming have/need and the source
    bad = c.post("/api/v1/actions", json={"action": "turn_in_quest", "params": {"quest_id": "q_ratcatcher"}}, headers=h)
    body = bad.json()["detail"]
    assert body["error"]["code"] == "INVALID_PARAMS"
    assert "3x Rat Pelt" in body["error"]["message"] and "Giant Rat" in body["error"]["message"]
    # partial stack still refused
    _give_quest_items(reg["agent_id"], "itm_rat_pelt", 2, "Rat Pelt")
    _set_hp_and_ready(reg["agent_id"], 25)
    short = c.post("/api/v1/actions", json={"action": "turn_in_quest", "params": {"quest_id": "q_ratcatcher"}}, headers=h)
    assert short.json()["detail"]["error"]["code"] == "INVALID_PARAMS"
    assert "you hold 2" in short.json()["detail"]["error"]["message"]
    # quest still active, progress reflects the partial stack
    st = c.get("/api/v1/status", headers=h).json()["data"]
    assert st["active_quests"][0]["progress"] == "2/3 Rat Pelt delivered"


def test_kills_alone_do_not_complete_item_quest():
    import json as _json
    from app.models import Agent as _A
    c = fresh_client()
    reg = register(c, "Grinder")
    h = {"Authorization": f"Bearer {reg['api_key']}"}
    _talk(c, h, reg["agent_id"], "npc_blacksmith")
    _set_hp_and_ready(reg["agent_id"], 25)
    assert c.post("/api/v1/actions", json={"action": "accept_quest", "params": {"quest_id": "q_ratcatcher"}}, headers=h).status_code == 200
    # simulate stored legacy kill-count fields: server must ignore them
    db = SessionLocal()
    a = db.query(_A).filter(_A.id == reg["agent_id"]).first()
    qs = _json.loads(a.quests)
    qs[0]["count"] = 99
    a.quests = _json.dumps(qs)
    db.commit()
    db.close()
    _set_hp_and_ready(reg["agent_id"], 25)
    bad = c.post("/api/v1/actions", json={"action": "turn_in_quest", "params": {"quest_id": "q_ratcatcher"}}, headers=h)
    assert bad.json()["detail"]["error"]["code"] == "INVALID_PARAMS"
    st = c.get("/api/v1/status", headers=h).json()["data"]
    assert st["active_quests"][0]["progress"] == "0/3 Rat Pelt delivered"


def _move(c, h, agent_id, to):
    _set_hp_and_ready(agent_id, 25)
    r = c.post("/api/v1/actions", json={"action": "move", "params": {"to": to}}, headers=h)
    assert r.status_code == 200, r.text
    return r.json()


def test_move_announces_every_npc_in_map():
    c = fresh_client()
    reg = register(c, "Newcomer")
    h = {"Authorization": f"Bearer {reg['api_key']}"}
    # Capital City holds 2 NPCs: arrival names both with roles + IDs
    out = _move(c, h, reg["agent_id"], "capital_city")
    ids = {n["npc_id"] for n in out["data"]["npcs"]}
    assert ids == {"npc_captain", "npc_merchant"}
    assert "quest-giver" in out["narrative"] and "talk_to_npc" in out["narrative"]
    assert out["data"]["monsters_present"] >= 2  # bandits stalk the capital
    assert "monster(s)" in out["narrative"]
    # Riverside Village holds 3 NPCs incl. the merchant: arrival names them all
    home = _move(c, h, reg["agent_id"], "riverside_village")
    home_ids = {n["npc_id"] for n in home["data"]["npcs"]}
    assert home_ids == {"npc_blacksmith", "npc_innkeeper", "npc_armorer_sella"}
    assert "Armorer Sella" in home["narrative"] and "npc_armorer_sella" in home["narrative"]
    assert "merchant" in home["narrative"] and "quest-giver" in home["narrative"]
    # Deep Cave holds no NPCs: arrival says so plainly
    _move(c, h, reg["agent_id"], "oakhollow_forest")
    cave = _move(c, h, reg["agent_id"], "deep_cave")
    assert cave["data"]["npcs"] == []
    assert "No NPCs here" in cave["narrative"]


def test_snapshot_carries_active_quests():
    c = fresh_client()
    reg = register(c, "QuestTracker")
    h = {"Authorization": f"Bearer {reg['api_key']}"}
    # fresh: no active quests in the snapshot
    _set_hp_and_ready(reg["agent_id"], 25)
    empty = c.post("/api/v1/actions", json={"action": "say",
                   "params": {"message": "hi"}}, headers=h).json()["data"]
    assert empty["active_quests"] == []
    # accept: quest appears inline with progress + return point
    _talk(c, h, reg["agent_id"], "npc_blacksmith")
    _set_hp_and_ready(reg["agent_id"], 25)
    acc = c.post("/api/v1/actions", json={"action": "accept_quest",
                 "params": {"quest_id": "q_ratcatcher"}}, headers=h).json()["data"]
    (q,) = acc["active_quests"]
    assert q["quest_id"] == "q_ratcatcher" and q["progress"] == "0/3 Rat Pelt delivered"
    assert q["turn_in_at"] == "riverside_village" and q["giver_npc"] == "npc_blacksmith"
    assert q["ready_talk"] is False
    # progress updates inline as loot lands: 2 pelts -> 2/3 without /status
    _give_quest_items(reg["agent_id"], "itm_rat_pelt", 2, "Rat Pelt")
    _set_hp_and_ready(reg["agent_id"], 25)
    prog = c.post("/api/v1/actions", json={"action": "say",
                  "params": {"message": "hunting"}}, headers=h).json()["data"]
    assert prog["active_quests"][0]["progress"] == "2/3 Rat Pelt delivered"
    # turn-in clears it from the snapshot
    _talk(c, h, reg["agent_id"], "npc_blacksmith")  # check-in while holding... still short
    _give_quest_items(reg["agent_id"], "itm_rat_pelt", 1, "Rat Pelt")
    _talk(c, h, reg["agent_id"], "npc_blacksmith")  # check-in with the full stack
    _set_hp_and_ready(reg["agent_id"], 25)
    done = c.post("/api/v1/actions", json={"action": "turn_in_quest",
                  "params": {"quest_id": "q_ratcatcher"}}, headers=h).json()["data"]
    assert done["active_quests"] == []
    assert done["player"]["quests_completed"] == 1


def _set_gold(agent_id, gold):
    from app.models import Agent as _A
    db = SessionLocal()
    a = db.query(_A).filter(_A.id == agent_id).first()
    a.gold = gold
    db.commit()
    db.close()
    from app.engine import _hits
    _hits.clear()


def _buy(c, h, agent_id, npc, iid):
    _set_hp_and_ready(agent_id, 25)
    r = c.post("/api/v1/actions", json={"action": "buy_item",
               "params": {"npc_id": npc, "item_id": iid}}, headers=h)
    return r


def _sell(c, h, agent_id, npc, iid, qty=1):
    _set_hp_and_ready(agent_id, 25)
    r = c.post("/api/v1/actions", json={"action": "sell_item",
               "params": {"npc_id": npc, "item_id": iid, "qty": qty}}, headers=h)
    return r


def test_merchant_talk_shows_tiered_shop_and_buyback():
    c = fresh_client()
    reg = register(c, "Shopper")
    h = {"Authorization": f"Bearer {reg['api_key']}"}
    # merchant lives at spawn: no travel needed
    t = _talk(c, h, reg["agent_id"], "npc_armorer_sella")
    shop = t["data"]["shop"]
    assert len(shop) >= 9, f"merchant should stock tiers of gear, got {len(shop)}"
    by_id = {s["item_id"]: s for s in shop}
    # tier bands by min_level: 1-2 cheap, 3-4 mid, 5+ best
    assert by_id["itm_short_sword"]["min_level"] == 1
    assert by_id["itm_knight_blade"]["min_level"] == 3
    assert by_id["itm_dragonslayer"]["min_level"] == 5
    # weapons +ATK, armor +DEF, potions heal — bonus and price rise with tier
    assert by_id["itm_short_sword"]["bonus"] == 2
    assert by_id["itm_knight_blade"]["bonus"] == 5
    assert by_id["itm_dragonslayer"]["bonus"] == 9
    assert by_id["itm_cloth_garb"]["defense"] == 1
    assert by_id["itm_chainmail"]["defense"] == 4
    assert by_id["itm_dragonscale_mail"]["defense"] == 7
    assert by_id["itm_healing_potion"]["heal"] == 12
    assert by_id["itm_greater_potion"]["heal"] == 25
    assert by_id["itm_elixir"]["heal"] == 45
    assert by_id["itm_dragonslayer"]["price"] > by_id["itm_knight_blade"]["price"] > by_id["itm_short_sword"]["price"]
    assert by_id["itm_dragonscale_mail"]["price"] > by_id["itm_chainmail"]["price"] > by_id["itm_cloth_garb"]["price"]
    assert all("level_ok" in s for s in shop)
    assert by_id["itm_dragonslayer"]["level_ok"] is False  # level 1 agent
    assert by_id["itm_short_sword"]["level_ok"] is True
    # buyback table scales with monster strength, plus gear resale at half price
    buys = {b["item_id"]: b["price"] for b in t["data"]["buys"]}
    kinds = {b["item_id"]: b["kind"] for b in t["data"]["buys"]}
    assert buys["itm_rat_pelt"] == 4 and buys["itm_drake_scale"] == 60
    assert buys["itm_rat_pelt"] < buys["itm_wolf_pelt"] < buys["itm_troll_hide"] < buys["itm_drake_scale"]
    assert kinds["itm_rat_pelt"] == "trophy"
    assert buys["itm_short_sword"] == 30 and kinds["itm_short_sword"] == "resale"  # half of 60g
    assert buys["itm_dragonslayer"] == 200  # half of 400g
    # old traders sell nothing anymore (same tile, no travel)
    t2 = _talk(c, h, reg["agent_id"], "npc_blacksmith")
    assert t2["data"]["shop"] == [] and t2["data"]["buys"] == []


def test_buy_gated_merchant_only():
    c = fresh_client()
    reg = register(c, "Buyer")
    h = {"Authorization": f"Bearer {reg['api_key']}"}
    # merchant lives at spawn: commerce starts at home
    # missing npc_id rejected up front
    _set_hp_and_ready(reg["agent_id"], 25)
    bad = c.post("/api/v1/actions", json={"action": "buy_item",
                 "params": {"item_id": "itm_short_sword"}}, headers=h)
    assert bad.json()["detail"]["error"]["code"] == "INVALID_PARAMS"
    # no talk yet: refused even standing in the right place
    _set_hp_and_ready(reg["agent_id"], 25)
    cold = c.post("/api/v1/actions", json={"action": "buy_item",
                  "params": {"npc_id": "npc_armorer_sella", "item_id": "itm_short_sword"}}, headers=h)
    assert cold.json()["detail"]["error"]["code"] == "TALK_FIRST"
    _talk(c, h, reg["agent_id"], "npc_armorer_sella")
    # broke (20g starting gold vs 60g sword)
    poor = _buy(c, h, reg["agent_id"], "npc_armorer_sella", "itm_short_sword")
    assert poor.json()["detail"]["error"]["code"] == "NOT_ENOUGH_GOLD"
    # under-level for T3 gear
    _set_gold(reg["agent_id"], 1000)
    locked = _buy(c, h, reg["agent_id"], "npc_armorer_sella", "itm_dragonslayer")
    assert locked.json()["detail"]["error"]["code"] == "QUEST_LOCKED"
    assert "level 5" in locked.json()["detail"]["error"]["message"]
    # success: gold deducted, item lands unequipped with its bonus
    _set_gold(reg["agent_id"], 1000)
    ok = _buy(c, h, reg["agent_id"], "npc_armorer_sella", "itm_short_sword")
    assert ok.status_code == 200, ok.text
    assert ok.json()["data"]["result"] == "bought"
    assert ok.json()["data"]["price"] == 60
    inv = c.get("/api/v1/status", headers=h).json()["data"]["inventory"]
    sword = next(i for i in inv if i["item_id"] == "itm_short_sword")
    assert sword["bonus"] == 2 and sword.get("equipped") is False
    assert c.get("/api/v1/status", headers=h).json()["data"]["gold"] == 940
    # old trader NPCs never sell, even on the same tile with a talk behind us
    _talk(c, h, reg["agent_id"], "npc_blacksmith")
    refuse = _buy(c, h, reg["agent_id"], "npc_blacksmith", "itm_short_sword")
    assert refuse.json()["detail"]["error"]["code"] == "TARGET_NOT_FOUND"
    # merchant sale from the wrong town is refused with the way back
    _move(c, h, reg["agent_id"], "capital_city")
    away = _buy(c, h, reg["agent_id"], "npc_armorer_sella", "itm_short_sword")
    assert away.json()["detail"]["error"]["code"] == "WRONG_LOCATION"
    assert "Riverside Village" in away.json()["detail"]["error"]["message"]


def test_sell_trophies_quest_protected():
    c = fresh_client()
    reg = register(c, "Seller")
    h = {"Authorization": f"Bearer {reg['api_key']}"}
    # merchant + quest giver share the home tile: no travel needed
    _talk(c, h, reg["agent_id"], "npc_armorer_sella")
    # no talk... covered; unknown goods and gear are not bought
    _set_hp_and_ready(reg["agent_id"], 25)
    gear = c.post("/api/v1/actions", json={"action": "sell_item",
                  "params": {"npc_id": "npc_armorer_sella", "item_id": "itm_rusty_sword", "qty": 1}}, headers=h)
    assert gear.json()["detail"]["error"]["code"] == "TARGET_NOT_FOUND"
    pot = _sell(c, h, reg["agent_id"], "npc_armorer_sella", "itm_healing_potion")
    assert pot.json()["detail"]["error"]["code"] == "TARGET_NOT_FOUND"
    # plain sale: 2 rat pelts -> +8g, stacks consumed
    _give_quest_items(reg["agent_id"], "itm_rat_pelt", 2, "Rat Pelt")
    before = c.get("/api/v1/status", headers=h).json()["data"]["gold"]
    done = _sell(c, h, reg["agent_id"], "npc_armorer_sella", "itm_rat_pelt", qty=2)
    assert done.status_code == 200, done.text
    assert done.json()["data"]["gold_gained"] == 8
    st = c.get("/api/v1/status", headers=h).json()["data"]
    assert st["gold"] == before + 8
    assert not any(i["item_id"] == "itm_rat_pelt" for i in st["inventory"])
    # overselling what you hold fails
    short = _sell(c, h, reg["agent_id"], "npc_armorer_sella", "itm_rat_pelt", qty=1)
    assert short.json()["detail"]["error"]["code"] == "INVALID_PARAMS"
    # quest block: accept ratcatcher (needs pelts), hold a surplus of 5 -> any sale blocked
    _talk(c, h, reg["agent_id"], "npc_blacksmith")
    _set_hp_and_ready(reg["agent_id"], 25)
    assert c.post("/api/v1/actions", json={"action": "accept_quest",
                  "params": {"quest_id": "q_ratcatcher"}}, headers=h).status_code == 200
    _give_quest_items(reg["agent_id"], "itm_rat_pelt", 5, "Rat Pelt")
    _talk(c, h, reg["agent_id"], "npc_armorer_sella")
    blocked = _sell(c, h, reg["agent_id"], "npc_armorer_sella", "itm_rat_pelt", qty=1)
    assert blocked.json()["detail"]["error"]["code"] == "INVALID_PARAMS"
    assert "active quest" in blocked.json()["detail"]["error"]["message"]
    # finish the quest (consumes 3, leaves 2) -> leftovers sell fine
    _talk(c, h, reg["agent_id"], "npc_blacksmith")  # check-in while holding the goods
    _set_hp_and_ready(reg["agent_id"], 25)
    assert c.post("/api/v1/actions", json={"action": "turn_in_quest",
                  "params": {"quest_id": "q_ratcatcher"}}, headers=h).status_code == 200
    _talk(c, h, reg["agent_id"], "npc_armorer_sella")
    before2 = c.get("/api/v1/status", headers=h).json()["data"]["gold"]
    ok = _sell(c, h, reg["agent_id"], "npc_armorer_sella", "itm_rat_pelt", qty=2)
    assert ok.status_code == 200, ok.text
    assert ok.json()["data"]["gold_gained"] == 8
    st2 = c.get("/api/v1/status", headers=h).json()["data"]
    assert st2["gold"] == before2 + 8
    assert not any(i["item_id"] == "itm_rat_pelt" for i in st2["inventory"])


def test_sell_gear_half_buy_price():
    c = fresh_client()
    reg = register(c, "Trader")
    h = {"Authorization": f"Bearer {reg['api_key']}"}
    _talk(c, h, reg["agent_id"], "npc_armorer_sella")
    _set_gold(reg["agent_id"], 1000)
    assert _buy(c, h, reg["agent_id"], "npc_armorer_sella", "itm_short_sword").status_code == 200
    assert _buy(c, h, reg["agent_id"], "npc_armorer_sella", "itm_cloth_garb").status_code == 200
    # used weapons/armor resell for half the buy price (60 -> 30)
    sold = _sell(c, h, reg["agent_id"], "npc_armorer_sella", "itm_short_sword")
    assert sold.status_code == 200, sold.text
    assert sold.json()["data"]["gold_gained"] == 30
    st = c.get("/api/v1/status", headers=h).json()["data"]
    assert st["gold"] == 1000 - 60 - 50 + 30
    assert not any(i["item_id"] == "itm_short_sword" for i in st["inventory"])
    # even equipped armor sells (auto-unequipped by the sale)
    _set_hp_and_ready(reg["agent_id"], 25)
    assert c.post("/api/v1/actions", json={"action": "equip_item",
                  "params": {"item_id": "itm_cloth_garb"}}, headers=h).status_code == 200
    sold2 = _sell(c, h, reg["agent_id"], "npc_armorer_sella", "itm_cloth_garb")
    assert sold2.status_code == 200, sold2.text
    assert sold2.json()["data"]["gold_gained"] == 25  # half of 50g
    assert not any(i["item_id"] == "itm_cloth_garb"
                   for i in c.get("/api/v1/status", headers=h).json()["data"]["inventory"])
    # potions are never bought back
    _set_hp_and_ready(reg["agent_id"], 25)
    no = c.post("/api/v1/actions", json={"action": "sell_item",
                "params": {"npc_id": "npc_armorer_sella", "item_id": "itm_greater_potion", "qty": 1}}, headers=h)
    assert no.json()["detail"]["error"]["code"] == "TARGET_NOT_FOUND"


def test_equip_weapon_and_armor_slots_with_defense():
    from app.engine import player_defense
    c = fresh_client()
    reg = register(c, "Tank")
    h = {"Authorization": f"Bearer {reg['api_key']}"}
    _talk(c, h, reg["agent_id"], "npc_armorer_sella")
    _set_gold(reg["agent_id"], 1000)
    assert _buy(c, h, reg["agent_id"], "npc_armorer_sella", "itm_short_sword").status_code == 200
    assert _buy(c, h, reg["agent_id"], "npc_armorer_sella", "itm_cloth_garb").status_code == 200
    # equip weapon then armor: both stay equipped (separate slots)
    _set_hp_and_ready(reg["agent_id"], 25)
    assert c.post("/api/v1/actions", json={"action": "equip_item",
                  "params": {"item_id": "itm_short_sword"}}, headers=h).status_code == 200
    _set_hp_and_ready(reg["agent_id"], 25)
    assert c.post("/api/v1/actions", json={"action": "equip_item",
                  "params": {"item_id": "itm_cloth_garb"}}, headers=h).status_code == 200
    inv = c.get("/api/v1/status", headers=h).json()["data"]["inventory"]
    assert next(i for i in inv if i["item_id"] == "itm_short_sword")["equipped"] is True
    assert next(i for i in inv if i["item_id"] == "itm_cloth_garb")["equipped"] is True
    # upgrading weapon keeps the armor on (iron sword needs level 2)
    _set_level(reg["agent_id"], 2)
    assert _buy(c, h, reg["agent_id"], "npc_armorer_sella", "itm_iron_sword").status_code == 200
    _set_hp_and_ready(reg["agent_id"], 25)
    assert c.post("/api/v1/actions", json={"action": "equip_item",
                  "params": {"item_id": "itm_iron_sword"}}, headers=h).status_code == 200
    inv2 = c.get("/api/v1/status", headers=h).json()["data"]["inventory"]
    assert next(i for i in inv2 if i["item_id"] == "itm_iron_sword")["equipped"] is True
    assert next(i for i in inv2 if i["item_id"] == "itm_short_sword")["equipped"] is False
    assert next(i for i in inv2 if i["item_id"] == "itm_cloth_garb")["equipped"] is True
    # defense math: fixed 5-damage hit reduced by 1 (cloth garb)
    import app.main as main_module
    from app.models import Agent as _A, Monster as _M
    db = SessionLocal()
    a = db.query(_A).filter(_A.id == reg["agent_id"]).first()
    assert player_defense(a) == 1
    db.close()
    _move(c, h, reg["agent_id"], "oakhollow_forest")
    db = SessionLocal()
    m = db.query(_M).filter(_M.location == "oakhollow_forest", _M.alive == True).first()  # noqa: E712
    m.hp = 200
    m.max_hp = 200
    mid = m.id
    db.commit()
    db.close()
    real = main_module.monster_attack_damage
    main_module.monster_attack_damage = lambda m: 5
    try:
        _set_hp_and_ready(reg["agent_id"], 25)
        out = c.post("/api/v1/actions", json={"action": "attack",
                     "params": {"target_id": mid}}, headers=h).json()
        assert out["data"]["result"] == "hit"
        assert out["data"]["damage_taken"] == 4  # 5 - 1 DEF
    finally:
        main_module.monster_attack_damage = real


def test_accept_requires_talk_at_giver():
    c = fresh_client()
    reg = register(c, "Eager")
    h = {"Authorization": f"Bearer {reg['api_key']}"}
    # no talk yet: refused even though we stand in the right place
    _set_hp_and_ready(reg["agent_id"], 25)
    no_talk = c.post("/api/v1/actions", json={"action": "accept_quest", "params": {"quest_id": "q_ratcatcher"}}, headers=h)
    assert no_talk.json()["detail"]["error"]["code"] == "TALK_FIRST"
    # talk, then accept works
    _talk(c, h, reg["agent_id"], "npc_blacksmith")
    _set_hp_and_ready(reg["agent_id"], 25)
    assert c.post("/api/v1/actions", json={"action": "accept_quest", "params": {"quest_id": "q_ratcatcher"}}, headers=h).status_code == 200
    # status advertises where to return
    st = c.get("/api/v1/status", headers=h).json()["data"]
    q = st["active_quests"][0]
    assert q["turn_in_at"] == "riverside_village" and q["giver_npc"] == "npc_blacksmith"
    assert q["ready_talk"] is False


def test_turn_in_requires_return_and_checkin_talk():
    c = fresh_client()
    reg = register(c, "Homesick")
    h = {"Authorization": f"Bearer {reg['api_key']}"}
    _talk(c, h, reg["agent_id"], "npc_blacksmith")
    _set_hp_and_ready(reg["agent_id"], 25)
    assert c.post("/api/v1/actions", json={"action": "accept_quest", "params": {"quest_id": "q_ratcatcher"}}, headers=h).status_code == 200
    _give_quest_items(reg["agent_id"], "itm_rat_pelt", 3, "Rat Pelt")
    # leave home: remote turn-in is refused with the way back
    _move(c, h, reg["agent_id"], "oakhollow_forest")
    _set_hp_and_ready(reg["agent_id"], 25)
    away = c.post("/api/v1/actions", json={"action": "turn_in_quest", "params": {"quest_id": "q_ratcatcher"}}, headers=h)
    assert away.json()["detail"]["error"]["code"] == "WRONG_LOCATION"
    assert "Riverside Village" in away.json()["detail"]["error"]["message"]
    # back home but no check-in talk since gathering the pelts: refused
    _move(c, h, reg["agent_id"], "riverside_village")
    _set_hp_and_ready(reg["agent_id"], 25)
    cold = c.post("/api/v1/actions", json={"action": "turn_in_quest", "params": {"quest_id": "q_ratcatcher"}}, headers=h)
    assert cold.json()["detail"]["error"]["code"] == "TALK_FIRST"
    # talk while holding the goods checks in, then turn-in succeeds
    t = _talk(c, h, reg["agent_id"], "npc_blacksmith")
    assert "turn_in_quest" in t["narrative"]
    assert c.get("/api/v1/status", headers=h).json()["data"]["active_quests"][0]["ready_talk"] is True
    _set_hp_and_ready(reg["agent_id"], 25)
    done = c.post("/api/v1/actions", json={"action": "turn_in_quest", "params": {"quest_id": "q_ratcatcher"}}, headers=h)
    assert done.status_code == 200, done.text
    assert done.json()["data"]["result"] == "quest_turned_in"
