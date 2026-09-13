"""Unit tests for the play.py heuristic (no server needed). Run: pytest -q"""
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

from play import decide

ZONES = [
    {"id": "riverside_village", "exits": [{"to": "oakhollow_forest"}, {"to": "capital_city"}]},
    {"id": "oakhollow_forest", "exits": [{"to": "riverside_village"}, {"to": "deep_cave"}]},
    {"id": "capital_city", "exits": [{"to": "riverside_village"}, {"to": "sunken_marsh"}]},
    {"id": "deep_cave", "exits": [{"to": "oakhollow_forest"}, {"to": "ember_ridge"}]},
    {"id": "sunken_marsh", "exits": [{"to": "capital_city"}, {"to": "ember_ridge"}]},
    {"id": "ember_ridge", "exits": [{"to": "deep_cave"}, {"to": "sunken_marsh"}]},
]


def _st(level=1, location="riverside_village", active=None, completed=None, hp=25, max_hp=25):
    return {"data": {"name": "T", "level": level, "hp": hp, "max_hp": max_hp,
                     "alive": True, "location": location, "inventory": [],
                     "active_quests": active or [], "completed_quests": completed or []}}


def _here(location="riverside_village", npcs=None, monsters=None, ground=None):
    exits = next(z["exits"] for z in ZONES if z["id"] == location)
    return {"data": {"location_id": location, "exits": exits, "npcs": npcs or [],
                     "monsters": monsters or [], "items_on_ground": ground or []}}


VILLAGE_NPCS = [{"npc_id": "npc_blacksmith"}, {"npc_id": "npc_innkeeper"}]
FOREST_NPCS = [{"npc_id": "npc_scout"}]


def test_post_turnin_lv1_grinds_forest_not_talk():
    """After q_ratcatcher turn-in at Lv1, village+completed offer => move to forest."""
    st = _st(level=1, completed=[{"quest_id": "q_ratcatcher"}])
    here = _here(npcs=VILLAGE_NPCS)
    offered = [{"quest_id": "q_ratcatcher", "level_ok": True, "completed": True,
                "status": "completed", "giver": "npc_blacksmith"}]
    act, params = decide(st, here, {}, offered=offered,
                         accepted={"q_ratcatcher"}, completed={"q_ratcatcher"}, zones=ZONES)
    assert act == "move" and params == {"to": "oakhollow_forest"}, (act, params)


def test_locked_offer_grinds():
    st = _st(level=1)
    here = _here(npcs=VILLAGE_NPCS)
    offered = [{"quest_id": "q_ratcatcher", "level_ok": True, "completed": True,
                "status": "completed", "giver": "npc_blacksmith"}]
    act, _ = decide(st, here, {}, offered=offered, accepted={"q_ratcatcher"}, zones=ZONES)
    assert act == "move"


def test_lv2_forest_accepts_wolfpack():
    st = _st(level=2, location="oakhollow_forest")
    here = _here(location="oakhollow_forest", npcs=FOREST_NPCS)
    offered = [{"quest_id": "q_wolfpack", "level_ok": True, "completed": False,
                "status": "available", "giver": "npc_scout"}]
    assert decide(st, here, {}, offered=offered, zones=ZONES) == \
        ("accept_quest", {"quest_id": "q_wolfpack"})


def test_stale_remote_offer_ignored():
    """Village-standing agent must not accept a forest quest remotely."""
    st = _st(level=2, completed=[{"quest_id": "q_ratcatcher"}])
    here = _here(npcs=VILLAGE_NPCS)
    offered = [{"quest_id": "q_ratcatcher", "level_ok": True, "completed": True,
                "status": "completed", "giver": "npc_blacksmith"},
               {"quest_id": "q_wolfpack", "level_ok": True, "completed": False,
                "status": "available", "giver": "npc_scout"}]
    act, params = decide(st, here, {}, offered=offered, accepted={"q_ratcatcher"},
                         completed={"q_ratcatcher"}, zones=ZONES)
    assert act == "move" and params["to"] in ("oakhollow_forest", "capital_city")


def test_repeat_talk_breaks_loop():
    st = _st(level=1, completed=[{"quest_id": "q_ratcatcher"}])
    here = _here(npcs=VILLAGE_NPCS)
    offered = [{"quest_id": "q_ratcatcher", "level_ok": True, "completed": True,
                "status": "completed", "giver": "npc_blacksmith"}]
    recent = [{"action": "talk_to_npc", "params": {"npc_id": "npc_blacksmith"}},
              {"action": "talk_to_npc", "params": {"npc_id": "npc_blacksmith"}}]
    act, _ = decide(st, here, {}, offered=offered, accepted={"q_ratcatcher"},
                    recent=recent, completed={"q_ratcatcher"}, zones=ZONES)
    assert act == "move"


def test_combat_first_at_grind_spot():
    st = _st(level=1, location="oakhollow_forest")
    here = _here(location="oakhollow_forest",
                 monsters=[{"monster_id": "mon_rat_1", "name": "Giant Rat", "hp": 8}])
    act, params = decide(st, here, {}, zones=ZONES)
    assert act == "attack" and params == {"target_id": "mon_rat_1"}
