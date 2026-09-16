"""Game-art resolver for the reference agent (stdlib only).

Every function here is fallback-first: missing assets/ dir, missing
manifest, missing SVG, or missing server asset fields must NEVER break
the turn loop — the caller gets emoji/text instead and play continues.
"""
import json
import os

LOCATION_EMOJI = {
    "riverside_village": "\U0001F3D8\uFE0F",
    "oakhollow_forest": "\U0001F332",
    "capital_city": "\U0001F3F0",
    "deep_cave": "\U0001F573\uFE0F",
    "sunken_marsh": "\U0001F30A",
    "ember_ridge": "\U0001F30B",
}
MONSTER_EMOJI = {
    "Giant Rat": "\U0001F400",
    "Forest Wolf": "\U0001F43A",
    "Road Bandit": "\U0001F977",
    "Marsh Wraith": "\U0001F47B",
    "Cave Troll": "\U0001F9CC",
    "Ember Drake": "\U0001F409",
}
KIND_EMOJI = {"weapon": "\u2694\uFE0F", "armor": "\U0001F6E1\uFE0F",
              "potion": "\U0001F9EA", "trophy": "\U0001F9B7"}


def find_assets_dir(cli_arg=""):
    """Locate the local assets/ checkout or return None (fallback mode)."""
    try:
        candidates = []
        if cli_arg:
            candidates.append(cli_arg)
        env = os.getenv("AIREALMS_ASSETS_DIR", "")
        if env:
            candidates.append(env)
        here = os.path.dirname(os.path.abspath(__file__))
        candidates.append(os.path.join(os.path.dirname(here), "..", "assets"))
        candidates.append(os.path.join(here, "..", "assets"))
        candidates.append(os.path.join(os.getcwd(), "assets"))
        for c in candidates:
            if c and os.path.isdir(c):
                return os.path.abspath(c)
    except Exception:
        pass
    return None


def load_manifest(assets_dir):
    """Read assets/manifest.json or return {} — never raises."""
    try:
        if not assets_dir:
            return {}
        path = os.path.join(assets_dir, "manifest.json")
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _local_file(assets_dir, rel):
    try:
        if not assets_dir or not rel:
            return None
        # rel looks like "assets/locations/x.svg"; allow both repo-relative
        # and dir-relative forms.
        base = os.path.basename(rel)
        parent = os.path.basename(os.path.dirname(rel)) or ""
        cand = os.path.join(assets_dir, parent, base) if parent else os.path.join(assets_dir, base)
        if os.path.exists(cand):
            return cand
        cand2 = os.path.join(assets_dir, rel.replace("assets/", ""))
        if os.path.exists(cand2):
            return cand2
    except Exception:
        pass
    return None


def _tag(assets_dir, rel, emoji):
    """One asset reference: local path if present, else the emoji fallback."""
    try:
        found = _local_file(assets_dir, rel)
        if found:
            return f"{emoji} [{found}]" if emoji else f"[{found}]"
    except Exception:
        pass
    return emoji or "(no art)"


def _expected(kind, key):
    try:
        if kind == "location":
            return f"assets/locations/{key}.svg"
        if kind == "monster":
            return f"assets/monsters/{(key or '').lower().replace(' ', '_')}.svg"
        if kind == "npc":
            return f"assets/npcs/{key}.svg"
        if kind == "item":
            return f"assets/items/{key}.svg"
    except Exception:
        pass
    return ""


def print_art(text):
    """Print art lines safely on any console (cp1252-safe).

    Tries the full emoji version first; on UnicodeEncodeError retries
    with emoji stripped so names/paths still show. Never raises.
    """
    try:
        print(text)
        return
    except UnicodeEncodeError:
        pass
    except Exception:
        return
    try:
        print("".join(c for c in str(text) if ord(c) < 128))
    except Exception:
        pass


def scene_block(me, here, assets_dir=None):
    """Render the per-turn Scene: block. Never raises; returns '' on failure."""
    try:
        me = (me or {}).get("data", me or {})
        world = (here or {}).get("data", here or {})
        loc_id = world.get("location_id") or me.get("location", "?")
        loc_rel = world.get("asset") or _expected("location", loc_id)
        lines = [f"Scene: {world.get('location_id', loc_id)} "
                 f"{_tag(assets_dir, loc_rel, LOCATION_EMOJI.get(loc_id, '')).strip()}".rstrip()]
        npcs = world.get("npcs", []) or []
        if npcs:
            bits = []
            for n in npcs[:4]:
                rel = n.get("asset") or _expected("npc", n.get("npc_id", ""))
                bits.append(f"{n.get('name', '?')} {_tag(assets_dir, rel, '\U0001F9D1')}")
            lines.append("  NPCs: " + "; ".join(bits))
        mons = world.get("monsters", []) or []
        if mons:
            bits = []
            for m in mons[:4]:
                rel = m.get("asset") or _expected("monster", m.get("name", ""))
                bits.append(f"{m.get('name', '?')} ({m.get('hp', '?')}/{m.get('max_hp', '?')} HP) "
                            f"{_tag(assets_dir, rel, MONSTER_EMOJI.get(m.get('name', ''), ''))}")
            lines.append("  Foes: " + "; ".join(bits))
        else:
            lines.append("  Foes: none here")
        loot = world.get("items_on_ground", []) or []
        if loot:
            bits = []
            for g in loot[:4]:
                rel = g.get("asset") or _expected("item", g.get("item_id", ""))
                bits.append(f"{g.get('name', '?')} x{g.get('qty', 1)} "
                            f"{_tag(assets_dir, rel, KIND_EMOJI.get('trophy', ''))}")
            lines.append("  Loot: " + "; ".join(bits))
        inv = me.get("inventory", []) or []
        gear = [i for i in inv if isinstance(i, dict) and i.get("equipped")]
        if gear:
            bits = []
            for i in gear[:2]:
                rel = i.get("asset") or _expected("item", i.get("item_id", ""))
                kind = i.get("kind", "weapon" if "attack" in i else "armor")
                bits.append(f"{i.get('name', '?')} {_tag(assets_dir, rel, KIND_EMOJI.get(kind, ''))}")
            lines.append("  You: " + ", ".join(bits))
        if assets_dir is None:
            lines.append("  (art fallback: assets/ not found — showing emoji)")
        return "\n".join(lines)
    except Exception:
        return ""


def loot_lines(result_data, assets_dir=None):
    """Render loot/level-up asset lines for an action result. Never raises."""
    try:
        data = (result_data or {}).get("data", result_data or {})
        out = []
        loot = (data.get("loot") or {})
        for item in (loot.get("items") or [])[:4]:
            rel = item.get("asset") or _expected("item", item.get("item_id", ""))
            out.append(f"Loot: {item.get('name', '?')} "
                       f"{_tag(assets_dir, rel, KIND_EMOJI.get('trophy', ''))}")
        player = data.get("player") or {}
        inv = player.get("inventory", []) or []
        fresh = [i for i in inv if isinstance(i, dict)
                 and str(i.get("item_id", "")).startswith("itm_")
                 and i.get("item_id") not in ("itm_rusty_sword", "itm_healing_potion")]
        # only surface on kill/buy/pick_up results to avoid spam
        if fresh and data.get("result") in ("kill", "bought", "picked_up"):
            last = fresh[-1]
            rel = last.get("asset") or _expected("item", last.get("item_id", ""))
            out.append(f"Gear: {last.get('name', '?')} "
                       f"{_tag(assets_dir, rel, KIND_EMOJI.get(last.get('kind', ''), ''))}")
        return out
    except Exception:
        return []
