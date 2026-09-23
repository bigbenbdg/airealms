"""Render a static preview of all six map stages with the seed-rule NPCs and
monsters for each location (from backend/app/seed.py). Useful for eyeballing
viewer.py stage layout changes without running the game.

Usage:
    python scripts/preview_scenes.py          # writes preview_scenes.html in repo root

Open the generated preview_scenes.html in a browser to review.
Stdlib + engines.viewer only; never mutates game state.
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "agent-starter"))
os.chdir(ROOT)

from engines.viewer import GameViewer  # noqa: E402


def main():
    v = GameViewer(assets_dir=os.path.abspath("assets"))
    me = {"name": "Sir Reginald Bot", "level": 3, "hp": 40, "max_hp": 50,
          "asset": "assets/player/player.png"}

    # NPCs / monsters mirror backend/app/seed.py spawns per location.
    SCENES = {
        "riverside_village": ("town", [
            {"name": "Old Toran", "npc_id": "npc_blacksmith", "asset": "assets/npcs/npc_blacksmith.png"},
            {"name": "Mira the Innkeep", "npc_id": "npc_innkeeper", "asset": "assets/npcs/npc_innkeeper.png"},
            {"name": "Armorer Sella", "npc_id": "npc_armorer_sella", "asset": "assets/npcs/npc_armorer_sella.png"},
        ], []),
        "oakhollow_forest": ("wild", [
            {"name": "Scout Liora", "npc_id": "npc_scout", "asset": "assets/npcs/npc_scout.png"},
        ], [
            {"name": "Giant Rat", "hp": 8, "max_hp": 8, "asset": "assets/monsters/giant_rat.png"},
            {"name": "Forest Wolf", "hp": 14, "max_hp": 14, "asset": "assets/monsters/forest_wolf.png"},
        ]),
        "capital_city": ("town", [
            {"name": "Captain Voss", "npc_id": "npc_captain", "asset": "assets/npcs/npc_captain.png"},
            {"name": "Merchant Pella", "npc_id": "npc_merchant", "asset": "assets/npcs/npc_merchant.png"},
        ], [
            {"name": "Road Bandit", "hp": 16, "max_hp": 16, "asset": "assets/monsters/road_bandit.png"},
        ]),
        "deep_cave": ("dungeon", [], [
            {"name": "Cave Troll", "hp": 30, "max_hp": 30, "asset": "assets/monsters/cave_troll.png"},
        ]),
        "sunken_marsh": ("wild", [
            {"name": "Marsh Hermit", "npc_id": "npc_hermit", "asset": "assets/npcs/npc_hermit.png"},
        ], [
            {"name": "Marsh Wraith", "hp": 22, "max_hp": 22, "asset": "assets/monsters/marsh_wraith.png"},
        ]),
        "ember_ridge": ("dungeon", [
            {"name": "Warden Cassia", "npc_id": "npc_warden", "asset": "assets/npcs/npc_warden.png"},
        ], [
            {"name": "Ember Drake", "hp": 45, "max_hp": 45, "asset": "assets/monsters/ember_drake.png"},
        ]),
    }

    out = os.path.join(ROOT, "preview_scenes.html")
    parts = ['<body style="background:#12141C;">']
    for loc, (ty, npcs, mons) in SCENES.items():
        world = {"location_id": loc, "type": ty, "npcs": npcs, "monsters": mons,
                 "items_on_ground": [], "exits": []}
        parts.append('<div style="max-width:900px;margin:12px auto;">'
                     + v._stage(me, world, loc, ty) + "</div>")
    parts.append("</body>")
    with open(out, "w", encoding="utf-8") as f:
        f.write("".join(parts))
    v.stop()
    print("wrote", out)


if __name__ == "__main__":
    main()
