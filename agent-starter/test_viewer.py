"""Regression tests for the reference agent's browser HUD."""
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from engines.viewer import GameViewer


def test_oakhollow_frame_with_ground_loot_is_visible():
    """Oakhollow's seeded loot must not collapse the whole HUD state."""
    assets_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "assets"))
    viewer = GameViewer(
        assets_dir=assets_dir,
        refresh=0,
        path=os.path.join(tempfile.gettempdir(), "airealms-viewer-regression.html"),
        port=0,
    )
    try:
        me = {
            "name": "Forest Browser",
            "level": 1,
            "hp": 25,
            "max_hp": 25,
            "gold": 0,
            "kills": 0,
            "location": "oakhollow_forest",
            "inventory": [],
            "active_quests": [],
        }
        here = {
            "location_id": "oakhollow_forest",
            "description": "Tall oaks drip with moss. Wolves prowl between the trees.",
            "exits": [
                {"to": "riverside_village", "direction": "back"},
                {"to": "deep_cave", "direction": "north"},
            ],
            "npcs": [{"npc_id": "npc_scout", "name": "Scout Liora"}],
            "monsters": [{
                "monster_id": "mon_rat_1",
                "name": "Giant Rat",
                "hp": 8,
                "max_hp": 8,
                "drops": {"name": "Rat Pelt", "chance": 1.0},
            }],
            "items_on_ground": [{
                "ground_id": "itm_wolf_pelt",
                "item_id": "itm_wolf_pelt",
                "name": "Wolf Pelt",
                "qty": 1,
            }],
        }
        viewer.update(1, {"data": me}, {"data": here}, "move", "Arrived", [], "playing")
        state = json.loads(viewer.state_json())

        assert state["loc_id"] == "oakhollow_forest"
        assert state["loc_name"] == "Oakhollow Forest"
        assert state["loc_type"] == "wild"
        assert "Tall oaks" in state["description"]
        assert "riverside_village" in state["exits_html"]
        assert state["tokens_svg"] and state["labels_svg"]
        assert "Giant Rat" in state["labels_svg"]
    finally:
        viewer.stop()
