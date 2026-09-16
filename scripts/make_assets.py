"""Generate procedural SVG game assets from assets.json (stdlib only).

Usage:
    python scripts/make_assets.py
    python scripts/make_assets.py --check   # exit 1 if any file missing

Reads repo-root assets.json (the 42-asset inventory) and writes
assets/locations/*.svg, assets/monsters/*.svg, assets/npcs/*.svg,
assets/items/*.svg plus assets/manifest.json mapping every id -> file.

Style matches frontend/src/App.jsx palette: INK #12141C, GOLD #C9A24B,
VERDIGRIS #4E9585, BLOOD #9E3B34, PARCHMENT #EDE7D9.
"""
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INVENTORY = os.path.join(ROOT, "assets.json")
ASSETS_DIR = os.path.join(ROOT, "assets")

INK = "#12141C"
GOLD = "#C9A24B"
VERDIGRIS = "#4E9585"
BLOOD = "#9E3B34"
PARCHMENT = "#EDE7D9"
SLATE = "#8FA0A8"

LOCATION_COLOR = {"town": GOLD, "wild": VERDIGRIS, "dungeon": BLOOD}
MONSTER_EMOJI = {
    "Giant Rat": "\U0001F400",
    "Forest Wolf": "\U0001F43A",
    "Road Bandit": "\U0001F977",
    "Marsh Wraith": "\U0001F47B",
    "Cave Troll": "\U0001F9CC",
    "Ember Drake": "\U0001F409",
}
LOCATION_EMOJI = {
    "riverside_village": "\U0001F3D8\uFE0F",
    "oakhollow_forest": "\U0001F332",
    "capital_city": "\U0001F3F0",
    "deep_cave": "\U0001F573\uFE0F",
    "sunken_marsh": "\U0001F30A",
    "ember_ridge": "\U0001F30B",
}


def _svg(body, label):
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 128 128" role="img">'
        f"<title>{label}</title>"
        f'<rect width="128" height="128" rx="16" fill="{INK}"/>'
        f"{body}</svg>\n"
    )


def location_svg(loc):
    color = LOCATION_COLOR.get(loc.get("type", ""), SLATE)
    emoji = LOCATION_EMOJI.get(loc["id"], "\u2753")
    glyph = ""
    if loc.get("type") == "town":
        glyph = (
            f'<polygon points="64,28 92,52 36,52" fill="{color}"/>'
            f'<rect x="44" y="52" width="40" height="36" fill="{INK}" '
            f'stroke="{color}" stroke-width="4"/>'
            f'<rect x="58" y="66" width="12" height="22" fill="{color}"/>'
        )
    elif loc.get("type") == "wild":
        glyph = (
            f'<g fill="{INK}" stroke="{color}" stroke-width="4">'
            '<polygon points="34,92 50,40 66,92"/>'
            '<polygon points="62,96 80,36 98,96"/></g>'
        )
    else:
        glyph = (
            f'<path d="M24,96 Q64,16 104,96 Z" fill="{INK}" '
            f'stroke="{color}" stroke-width="4"/>'
            f'<ellipse cx="64" cy="80" rx="16" ry="11" fill="#0B0D13" '
            f'stroke="{color}" stroke-width="2"/>'
        )
    body = (
        f"{glyph}"
        f'<text x="64" y="116" text-anchor="middle" font-size="13" '
        f'fill="{PARCHMENT}" font-family="Georgia,serif">{loc["name"][:18]}</text>'
        f'<text x="112" y="24" text-anchor="middle" font-size="20">{emoji}</text>'
    )
    return _svg(body, loc["name"])


def monster_svg(mon):
    emoji = MONSTER_EMOJI.get(mon["name"], "\u2753")
    hp = mon.get("hp", 10)
    ring = 7 if hp >= 30 else 5
    body = (
        f'<circle cx="64" cy="58" r="30" fill="#241318" stroke="{BLOOD}" '
        f'stroke-width="{ring}"/>'
        f'<text x="64" y="70" text-anchor="middle" font-size="34">{emoji}</text>'
        f'<text x="64" y="108" text-anchor="middle" font-size="12" '
        f'fill="{PARCHMENT}" font-family="Georgia,serif">{mon["name"][:18]}</text>'
    )
    return _svg(body, mon["name"])


def npc_svg(npc):
    initial = (npc.get("name") or "?").strip()[:1].upper()
    color = VERDIGRIS if npc.get("role") == "merchant" else GOLD
    body = (
        f'<circle cx="64" cy="54" r="28" fill="{INK}" stroke="{color}" '
        'stroke-width="4"/>'
        f'<text x="64" y="66" text-anchor="middle" font-size="30" '
        f'fill="{PARCHMENT}" font-family="Georgia,serif" font-weight="bold">'
        f"{initial}</text>"
        f'<text x="64" y="104" text-anchor="middle" font-size="11" '
        f'fill="{PARCHMENT}" font-family="Georgia,serif">{npc["name"][:18]}</text>'
        f'<text x="64" y="117" text-anchor="middle" font-size="9" fill="{SLATE}">'
        f"{npc.get('role', '')[:18]}</text>"
    )
    return _svg(body, npc["name"])


ITEM_EMOJI = {
    "weapon": "\u2694\uFE0F",
    "armor": "\U0001F6E1\uFE0F",
    "potion": "\U0001F9EA",
    "trophy": "\U0001F9B7",
}


def item_svg(item):
    kind = item.get("kind", "trophy")
    emoji = ITEM_EMOJI.get(kind, "\U0001F4E6")
    edge = GOLD if kind in ("weapon", "trophy") else VERDIGRIS if kind == "armor" else BLOOD
    body = (
        f'<polygon points="64,22 88,54 64,86 40,54" fill="{INK}" '
        f'stroke="{edge}" stroke-width="4"/>'
        f'<text x="64" y="64" text-anchor="middle" font-size="22">{emoji}</text>'
        f'<text x="64" y="106" text-anchor="middle" font-size="11" '
        f'fill="{PARCHMENT}" font-family="Georgia,serif">{item["name"][:18]}</text>'
    )
    return _svg(body, item["name"])


def main():
    check_only = "--check" in sys.argv
    with open(INVENTORY, encoding="utf-8") as f:
        inv = json.load(f)
    jobs = []
    for loc in inv.get("locations", []):
        jobs.append((loc["file"], location_svg(loc)))
    for mon in inv.get("monsters", []):
        key = mon["name"].lower().replace(" ", "_")
        jobs.append((f"assets/monsters/{key}.svg", monster_svg(mon)))
    for npc in inv.get("npcs", []):
        jobs.append((npc["file"], npc_svg(npc)))
    for item in inv.get("items", []):
        jobs.append((item["file"], item_svg(item)))

    # Blender-rendered map backgrounds (scripts/make_backgrounds.py) are
    # checked for presence but never generated here — they need Blender.
    backgrounds = inv.get("backgrounds", {}) or {}
    missing = [rel for rel, _ in jobs
               if not os.path.exists(os.path.join(ROOT, rel))]
    missing_bg = [rel for rel in backgrounds.values()
                  if not os.path.exists(os.path.join(ROOT, rel))]
    if check_only:
        if missing:
            print(f"Missing {len(missing)} asset files:")
            for m in missing:
                print(f"  {m}")
        if missing_bg:
            print(f"Missing {len(missing_bg)} background files "
                  f"(run in Blender: scripts/make_backgrounds.py):")
            for m in missing_bg:
                print(f"  {m}")
        if missing or missing_bg:
            return 1
        print(f"All {len(jobs)} asset files + {len(backgrounds)} backgrounds present.")
        return 0

    for rel, content in jobs:
        path = os.path.join(ROOT, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8", newline="\n") as f:
            f.write(content)

    manifest = {"version": inv.get("version", "1.0.0"), "locations": {},
                "monsters": {}, "npcs": {}, "items": {}, "backgrounds": {}}
    for loc in inv.get("locations", []):
        manifest["locations"][loc["id"]] = loc["file"]
    for mon in inv.get("monsters", []):
        key = mon["name"].lower().replace(" ", "_")
        manifest["monsters"][mon["name"]] = f"assets/monsters/{key}.svg"
    for npc in inv.get("npcs", []):
        manifest["npcs"][npc["npc_id"]] = npc["file"]
    for item in inv.get("items", []):
        manifest["items"][item["item_id"]] = item["file"]
    for loc_id, rel in backgrounds.items():
        manifest["backgrounds"][loc_id] = rel
    with open(os.path.join(ASSETS_DIR, "manifest.json"), "w",
              encoding="utf-8", newline="\n") as f:
        json.dump(manifest, f, indent=2)
        f.write("\n")
    print(f"Wrote {len(jobs)} SVG files + assets/manifest.json.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
