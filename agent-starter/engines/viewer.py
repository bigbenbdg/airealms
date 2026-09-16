"""In-game viewer for the reference agent (stdlib only).

`python play.py --view` writes a self-contained `viewer.html` every turn
(SVG art inlined, so no web server or asset paths needed) and opens it
once in your browser. The page auto-refreshes via `<meta refresh>`, so it
plays like a little side-view game scene while the CLI loop runs:

  background (trees / town / cave) + road ── character, monsters, loot,
  NPCs standing on one stage, with HP bars and names, then the HUD panels
  (pack, quests, adventure log) underneath.

Fallback-first like engines/assets.py: missing SVGs become shapes/emoji,
missing state becomes "?", and no exception ever escapes into the turn loop.
Set AIREALMS_NO_BROWSER=1 to write the file without popping a browser
(useful for tests / headless runs).
"""
import html
import os
import tempfile

from engines.assets import _local_file, _expected

INK = "#12141C"
PANEL = "#1B1F2C"
GOLD = "#C9A24B"
VERDIGRIS = "#4E9585"
BLOOD = "#9E3B34"
SLATE = "#8FA0A8"
PARCHMENT = "#EDE7D9"
HAIRLINE = "#2C3244"

# Stage palette per location type (matches the spectator frontend).
SKY = {"town": "#1E2436", "wild": "#16241F", "dungeon": "#1A1218"}
GROUND = {"town": "#141824", "wild": "#101812", "dungeon": "#120D12"}
DECOR = {"town": GOLD, "wild": VERDIGRIS, "dungeon": BLOOD}


def _esc(value):
    try:
        return html.escape(str(value), quote=True)
    except Exception:
        return "?"


def _hp_color(hp, max_hp):
    try:
        pct = float(hp) / float(max_hp or 1)
    except Exception:
        return SLATE
    if pct > 0.5:
        return VERDIGRIS
    if pct > 0.25:
        return GOLD
    return BLOOD


def _svg_or_emoji(assets_dir, rel, emoji, size=64):
    """Inline SVG <size>px square, or a big emoji fallback. Never raises."""
    try:
        path = _local_file(assets_dir, rel or "")
        if path:
            with open(path, encoding="utf-8") as f:
                svg = f.read()
            # force display size; keep the artwork itself untouched
            svg = svg.replace('viewBox="0 0 128 128"',
                              f'width="{size}" height="{size}" viewBox="0 0 128 128"', 1)
            return svg
    except Exception:
        pass
    try:
        return (f'<div style="width:{size}px;height:{size}px;font-size:{size // 2}px;'
                f'display:flex;align-items:center;justify-content:center;">'
                f'{_esc(emoji or "?")}</div>')
    except Exception:
        return "?"


def _asset_inner(assets_dir, rel):
    """Inner markup of an asset SVG (without its outer <svg> tag), or None."""
    try:
        path = _local_file(assets_dir, rel or "")
        if not path:
            return None
        with open(path, encoding="utf-8") as f:
            svg = f.read()
        start = svg.find(">")
        end = svg.find("</svg>")
        if start < 0 or end < 0 or end <= start:
            return None
        return svg[start + 1:end]
    except Exception:
        return None


def _nested_art(assets_dir, rel, x, y, size, ring_color, label="?"):
    """Place asset artwork on the stage; falls back to a ringed token."""
    try:
        inner = _asset_inner(assets_dir, rel)
        if inner:
            return (f'<svg x="{x}" y="{y}" width="{size}" height="{size}" '
                    f'viewBox="0 0 128 128">{inner}</svg>')
    except Exception:
        pass
    cx, cy, r = x + size / 2, y + size / 2, size / 2 - 2
    return (f'<circle cx="{cx}" cy="{cy}" r="{r}" fill="{INK}" '
            f'stroke="{ring_color}" stroke-width="4"/>'
            f'<text x="{cx}" y="{cy + 8}" text-anchor="middle" font-size="24" '
            f'fill="{PARCHMENT}" font-weight="bold">{_esc((label or "?")[:1])}</text>')


def _svg_bar(x, y, w, hp, max_hp, h=8, label=True):
    """HP bar drawn in stage coordinates. Never raises."""
    try:
        pct = max(0.0, min(1.0, float(hp) / float(max_hp or 1)))
    except Exception:
        pct, hp, max_hp = 0.0, "?", "?"
    color = _hp_color(hp, max_hp)
    fill = max(2, int((w - 2) * pct))
    out = (f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{h / 2}" '
           f'fill="#0B0D13" stroke="{HAIRLINE}"/>'
           f'<rect x="{x + 1}" y="{y + 1}" width="{fill}" height="{h - 2}" '
           f'rx="{(h - 2) / 2}" fill="{color}"/>')
    if label:
        out += (f'<text x="{x + w / 2}" y="{y + h + 13}" text-anchor="middle" '
                f'font-size="12" fill="{PARCHMENT}">{_esc(hp)}/{_esc(max_hp)}</text>')
    return out


def _pines(xs, base_y, scale, color, opacity=1.0):
    """A cluster of pine trees (the sketch's background)."""
    parts = []
    for x in xs:
        w, h = 46 * scale, 90 * scale
        parts.append(
            f'<g opacity="{opacity}" stroke="{color}" stroke-width="3" fill="{INK}">'
            f'<polygon points="{x},{base_y} {x + w / 2},{base_y - h} {x + w},{base_y}"/>'
            f'<line x1="{x + w / 2}" y1="{base_y}" x2="{x + w / 2}" y2="{base_y + 14 * scale}"/>'
            f'</g>')
    return "".join(parts)


def _bar(hp, max_hp, width=120):
    try:
        pct = max(0.0, min(1.0, float(hp) / float(max_hp or 1)))
    except Exception:
        pct = 0.0
    color = _hp_color(hp, max_hp)
    fill = int(width * pct)
    return (f'<div style="background:#0B0D13;border:1px solid #2C3244;border-radius:4px;'
            f'width:{width}px;height:10px;">'
            f'<div style="background:{color};width:{fill}px;height:8px;border-radius:3px;"></div></div>'
            f'<div style="font-size:11px;color:{SLATE};">{_esc(hp)}/{_esc(max_hp)}</div>')


class GameViewer:
    """Writes viewer.html every turn; browser auto-refreshes. Never raises."""

    def __init__(self, assets_dir=None, refresh=2, path=""):
        self.assets_dir = assets_dir
        self.refresh = max(0, int(refresh or 0))
        try:
            self.path = os.path.abspath(path) if path else os.path.join(
                tempfile.gettempdir(), "airealms-viewer.html")
        except Exception:
            self.path = os.path.join(tempfile.gettempdir(), "airealms-viewer.html")
        self._opened = False

    def open(self):
        """Pop the browser once. Honors AIREALMS_NO_BROWSER=1. Never raises."""
        if self._opened:
            return
        self._opened = True
        try:
            if os.getenv("AIREALMS_NO_BROWSER", "").lower() in ("1", "true", "yes", "on"):
                return
            import webbrowser
            webbrowser.open(f"file:///{self.path.replace(os.sep, '/')}")
        except Exception:
            pass

    def update(self, turn=0, me=None, here=None, action_desc="",
               result_narrative="", log=None, status="playing"):
        """Render one frame. All args optional; never raises."""
        try:
            page = self._render(turn, me or {}, here or {},
                                action_desc, result_narrative, log or [], status)
            tmp = self.path + ".tmp"
            with open(tmp, "w", encoding="utf-8", newline="\n") as f:
                f.write(page)
            os.replace(tmp, self.path)
        except Exception:
            pass

    # -- internals -----------------------------------------------------
    def _stage(self, me, world, loc_id, loc_type):
        """Side-view game scene: background, road, character, monsters, loot, NPCs."""
        ad = self.assets_dir
        sky = SKY.get(loc_type, "#181C28")
        ground = GROUND.get(loc_type, "#12141C")
        decor = DECOR.get(loc_type, SLATE)

        parts = [f'<rect x="0" y="0" width="960" height="380" rx="10" fill="{sky}"/>']

        # Backdrop per terrain (the sketch's trees / town / cave).
        if loc_type == "wild":
            parts.append(_pines([30, 110, 830, 890], 300, 1.1, VERDIGRIS, 0.9))
            parts.append(_pines([180, 760], 300, 0.7, VERDIGRIS, 0.5))
        elif loc_type == "town":
            parts.append(
                f'<g opacity="0.85" stroke="{GOLD}" fill="{INK}" stroke-width="3">'
                f'<polygon points="770,150 850,100 930,150"/>'
                f'<rect x="785" y="150" width="130" height="90"/>'
                f'<rect x="835" y="190" width="30" height="50" fill="{GOLD}"/>'
                f'<polygon points="60,180 120,140 180,180"/>'
                f'<rect x="72" y="180" width="96" height="60"/>'
                f'</g>')
        elif loc_type == "dungeon":
            parts.append(
                f'<ellipse cx="700" cy="20" rx="260" ry="70" fill="{BLOOD}" opacity="0.18"/>'
                f'<g fill="{HAIRLINE}">'
                f'<polygon points="80,0 100,0 90,46"/><polygon points="420,0 444,0 432,58"/>'
                f'<polygon points="700,0 720,0 710,44"/><polygon points="880,0 898,0 889,40"/>'
                f'</g>')
        else:
            parts.append(_pines([40, 880], 300, 0.9, SLATE, 0.6))

        # Road: the sketch's diagonal path across the scene.
        parts.append(
            f'<polygon points="40,380 470,0 610,0 180,380" fill="{HAIRLINE}" opacity="0.55"/>'
            f'<line x1="40" y1="380" x2="470" y2="0" stroke="{SLATE}" opacity="0.6"/>'
            f'<line x1="180" y1="380" x2="610" y2="0" stroke="{SLATE}" opacity="0.6"/>')
        # Ground strip.
        parts.append(f'<rect x="0" y="300" width="960" height="80" fill="{ground}" opacity="0.9"/>')

        # NPCs: standing figures along the back.
        npcs = [n for n in (world.get("npcs", []) or []) if isinstance(n, dict)][:4]
        for i, n in enumerate(npcs):
            x = 250 + i * 70
            parts.append(_nested_art(ad, n.get("asset") or _expected("npc", n.get("npc_id", "")),
                                     x, 96, 52, VERDIGRIS, n.get("name", "?")))
            parts.append(f'<text x="{x + 26}" y="164" text-anchor="middle" font-size="12" '
                         f'fill="{PARCHMENT}">{_esc(n.get("name", "?"))}</text>')

        # Character: the hero, front-left on the road (the sketch's circle).
        name = me.get("name", "?") if isinstance(me, dict) else "?"
        initial = (str(name).strip()[:1] or "?").upper()
        cx = 150
        parts.append(_svg_bar(cx - 45, 196, 90, me.get("hp", 0), me.get("max_hp", 0)))
        parts.append(f'<circle cx="{cx}" cy="262" r="36" fill="{INK}" '
                     f'stroke="{GOLD}" stroke-width="5"/>'
                     f'<text x="{cx}" y="274" text-anchor="middle" font-size="32" '
                     f'fill="{PARCHMENT}" font-weight="bold" '
                     f'font-family="Georgia,serif">{_esc(initial)}</text>'
                     f'<text x="{cx}" y="316" text-anchor="middle" font-size="14" '
                     f'fill="{GOLD}" font-weight="bold">{_esc(name)} · Lv {_esc(me.get("level", "?"))}</text>')

        # Monsters: mid-scene and right, each with HP bar + drop glint.
        mons = [m for m in (world.get("monsters", []) or []) if isinstance(m, dict)][:4]
        for i, m in enumerate(mons):
            x = 430 + i * 135
            y = 150 if i % 2 == 0 else 205
            parts.append(_svg_bar(x - 8, y - 34, 96, m.get("hp", 0), m.get("max_hp", 0)))
            parts.append(_nested_art(ad, m.get("asset") or _expected("monster", m.get("name", "")),
                                     x, y, 80, BLOOD, m.get("name", "?")))
            parts.append(f'<text x="{x + 40}" y="{y + 98}" text-anchor="middle" font-size="13" '
                         f'fill="{PARCHMENT}">{_esc(m.get("name", "?"))}</text>')
            if (m.get("drops") or {}).get("name"):
                parts.append(f'<circle cx="{x + 72}" cy="{y + 6}" r="7" fill="{GOLD}">'
                             f'<title>{_esc(m["drops"]["name"])}</title></circle>')
        extra_mons = len([m for m in (world.get("monsters", []) or []) if isinstance(m, dict)]) - len(mons)
        if extra_mons > 0:
            parts.append(f'<text x="920" y="200" text-anchor="middle" font-size="14" '
                         f'fill="{SLATE}">+{extra_mons} more</text>')
        if not mons:
            parts.append(f'<text x="620" y="200" text-anchor="middle" font-size="15" '
                         f'fill="{SLATE}">No monsters — safe to rest.</text>')

        # Loot: small glints on the ground (the sketch's little loot circle).
        loot = [g for g in (world.get("items_on_ground", []) or []) if isinstance(g, dict)][:4]
        for i, g in enumerate(loot):
            x = 330 + i * 80
            parts.append(_nested_art(ad, g.get("asset") or _expected("item", g.get("item_id", "")),
                                     x, 288, 44, GOLD, g.get("name", "?")))
            qty = f' x{g.get("qty", 1)}' if g.get("qty", 1) != 1 else ""
            parts.append(f'<text x="{x + 22}" y="352" text-anchor="middle" font-size="12" '
                         f'fill="{GOLD}">{_esc(g.get("name", "?"))}{_esc(qty)}</text>')

        # Caption: location name + terrain tag.
        loc_name = world.get("location_id", loc_id)
        parts.append(f'<text x="16" y="34" font-size="24" fill="{PARCHMENT}" '
                     f'font-family="Georgia,serif">{_esc(loc_name)}</text>')
        parts.append(f'<text x="944" y="34" font-size="13" fill="{decor}" text-anchor="end">'
                     f'{_esc(loc_type or "?")}</text>')

        return (f'<svg viewBox="0 0 960 380" style="width:100%;height:auto;display:block;">'
                f'{"".join(parts)}</svg>')

    def _render(self, turn, me_raw, here_raw, action_desc, result_narrative, log, status):
        me = me_raw.get("data", me_raw) if isinstance(me_raw, dict) else {}
        world = here_raw.get("data", here_raw) if isinstance(here_raw, dict) else {}
        if not isinstance(me, dict):
            me, world = {}, {}
        if not isinstance(world, dict):
            world = {}

        name = me.get("name", "?")
        level = me.get("level", "?")
        hp, max_hp = me.get("hp", "?"), me.get("max_hp", "?")
        gold = me.get("gold", "?")
        kills = me.get("kills", "?")
        loc_id = world.get("location_id") or me.get("location", "?")
        loc_type = None
        for cand in (world.get("type"),):
            if cand in ("town", "wild", "dungeon"):
                loc_type = cand
        if loc_type is None:
            loc_type = {"riverside_village": "town", "capital_city": "town",
                        "oakhollow_forest": "wild", "sunken_marsh": "wild",
                        "deep_cave": "dungeon", "ember_ridge": "dungeon"}.get(loc_id)

        stage = self._stage(me, world, loc_id, loc_type)

        inv = [i for i in (me.get("inventory", []) or []) if isinstance(i, dict)][:10]
        inv_rows = []
        for i in inv:
            art = _svg_or_emoji(self.assets_dir,
                                i.get("asset") or _expected("item", i.get("item_id", "")),
                                "?", size=32)
            star = " ⭐" if i.get("equipped") else ""
            inv_rows.append(
                f'<div style="display:flex;gap:8px;align-items:center;padding:3px 0;">{art}'
                f'<span style="color:{PARCHMENT};font-size:13px;">{_esc(i.get("name", "?"))} '
                f'x{_esc(i.get("qty", 1))}{star}</span></div>')
        inv_html = "".join(inv_rows) if inv_rows else \
            f'<div style="color:{SLATE};">Empty pack.</div>'

        quests = [q for q in (me.get("active_quests", []) or []) if isinstance(q, dict)][:6]
        quest_rows = "".join(
            f'<div style="padding:3px 0;font-size:13px;color:{PARCHMENT};">'
            f'⚔ {_esc(q.get("title", "?"))} — {_esc(q.get("progress", "?"))}</div>'
            for q in quests) or f'<div style="color:{SLATE};">No active quests.</div>'

        exits = [e.get("to", "?") for e in (world.get("exits", []) or []) if isinstance(e, dict)]
        exits_html = " ".join(
            f'<span style="background:{PANEL};border:1px solid {GOLD};color:{GOLD};'
            f'border-radius:12px;padding:2px 10px;margin:2px;font-size:12px;">{_esc(e)}</span>'
            for e in exits) or f'<span style="color:{SLATE};">no exits</span>'

        log_html = "".join(
            f'<div style="padding:4px 0;border-bottom:1px solid #2C3244;font-size:13px;'
            f'color:{PARCHMENT};">{_esc(entry)}</div>'
            for entry in list(log or [])[-12:][::-1]) or \
            f'<div style="color:{SLATE};">Log is empty.</div>'

        refresh_tag = (f'<meta http-equiv="refresh" content="{self.refresh}">' if self.refresh else "")
        banner = ""
        if status == "dead":
            banner = (f'<div style="background:{BLOOD};color:#fff;text-align:center;'
                      f'padding:8px;font-weight:bold;">☠ YOU DIED — see the CLI debrief ☠</div>')

        return ("<!DOCTYPE html><html><head><meta charset='utf-8'>" + refresh_tag +
                f"<title>AI Realms — {_esc(name)} @ {_esc(loc_id)}</title></head>"
                f'<body style="background:{INK};color:{PARCHMENT};font-family:system-ui,sans-serif;margin:0;">'
                + banner +
                f'<div style="padding:12px 16px;border-bottom:1px solid #2C3244;display:flex;'
                f'gap:16px;align-items:center;flex-wrap:wrap;">'
                f'<div style="font-family:Georgia,serif;font-size:22px;">⚔ AI Realms</div>'
                f'<div style="font-size:20px;">{_esc(name)} <span style="color:{GOLD};">Lv {_esc(level)}</span></div>'
                f'{_bar(hp, max_hp)}'
                f'<div>🪙 {_esc(gold)} gold</div><div>💀 {_esc(kills)} kills</div>'
                f'<div style="color:{SLATE};">turn {_esc(turn)} · {_esc(status)}</div>'
                f'<div style="color:{SLATE};font-size:12px;">auto-refreshes every {self.refresh}s</div>'
                f'</div>'
                f'<div style="padding:12px 16px 0;">'
                f'<div style="background:{PANEL};border:1px solid #2C3244;border-radius:10px;padding:12px;">'
                f'{stage}'
                f'<div style="font-size:13px;color:{SLATE};margin-top:8px;">{_esc(world.get("description", ""))}</div>'
                f'<div style="margin-top:6px;">{exits_html}</div>'
                f'</div>'
                f'</div>'
                f'<div style="display:flex;gap:12px;padding:12px 16px;flex-wrap:wrap;">'
                f'<div style="flex:1;min-width:240px;background:{PANEL};border:1px solid #2C3244;'
                f'border-radius:10px;padding:12px;">'
                f'<div style="font-size:12px;color:{SLATE};">PACK</div>{inv_html}'
                f'<div style="font-size:12px;color:{SLATE};margin-top:8px;">QUESTS</div>{quest_rows}'
                f'</div>'
                f'<div style="flex:2;min-width:300px;background:{PANEL};border:1px solid #2C3244;'
                f'border-radius:10px;padding:12px;">'
                f'<div style="font-size:12px;color:{SLATE};">LAST ACTION</div>'
                f'<div style="font-size:13px;">{_esc(action_desc or "—")}</div>'
                f'<div style="font-size:13px;color:{VERDIGRIS};">{_esc(result_narrative or "")}</div>'
                f'<div style="font-size:12px;color:{SLATE};margin-top:8px;">ADVENTURE LOG</div>{log_html}'
                f'</div>'
                f'</div>'
                f'</body></html>')
