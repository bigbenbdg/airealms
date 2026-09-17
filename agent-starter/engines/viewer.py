"""In-game viewer for the reference agent (stdlib only).

`python play.py --view` serves a live game HUD on 127.0.0.1 (stdlib
http.server, no full-page reload) and opens it once in your browser. The page
fetches `state.json` and patches only what changed — backdrop image
crossfades, tokens/HUD update in place — so there is no 2s flicker:

  Blender-rendered map background (assets/backgrounds/<loc>.png) or a
  procedurally drawn one when that art is missing, with the character,
  monsters, loot and NPCs standing on the scene's ground line, then the HUD
  panels (pack, quests, adventure log) underneath.

A file snapshot (`viewer.html` + `viewer-state.json`) is still written every
turn for headless runs / debugging; the file copy keeps the legacy
`<meta refresh>` fallback when the local server cannot bind.

Fallback-first like engines/assets.py: missing backgrounds fall back to drawn
terrain, missing art (SVG locations/items, PNG monsters/NPCs) becomes shapes/emoji, missing state becomes "?", and no
exception ever escapes into the turn loop. Set AIREALMS_NO_BROWSER=1 to write
the files without popping a browser (useful for tests / headless runs).
"""
import html
import json
import mimetypes
import os
import tempfile
import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

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

STAGE_W, STAGE_H = 960, 540
# Per-map stage layout in 960x540 coordinates (y=0 top). Validated in Blender
# against assets/backgrounds/*.png (2848x1600, aspect 1.78 == 960/540) by
# compositing each sprite as an alpha plane over the backdrop and rendering.
# npc_y = feet line of the back row (smaller, further away); player_feet /
# monster_feet = front-row feet; loot_y = ground-pile row. x slots keep each
# map's focal point clear (village river, city gate stairs, cave crystals,
# marsh water, ridge lava lake).
STAGE_LAYOUT = {
    "riverside_village": {"npc_y": 400, "player_feet": 470, "monster_feet": 460,
                          "loot_y": 488, "player_x": 150, "npc_x0": 300,
                          "monster_x0": 600},
    "oakhollow_forest": {"npc_y": 395, "player_feet": 470, "monster_feet": 461,
                         "loot_y": 488, "player_x": 150, "npc_x0": 420,
                         "monster_x0": 600},
    "capital_city": {"npc_y": 440, "player_feet": 475, "monster_feet": 465,
                     "loot_y": 490, "player_x": 150, "npc_x0": 300,
                     "monster_x0": 680},
    "deep_cave": {"npc_y": 410, "player_feet": 470, "monster_feet": 465,
                  "loot_y": 488, "player_x": 170, "npc_x0": 400,
                  "monster_x0": 620},
    "sunken_marsh": {"npc_y": 400, "player_feet": 475, "monster_feet": 450,
                      "loot_y": 492, "player_x": 150, "npc_x0": 450,
                      "monster_x0": 660},
    "ember_ridge": {"npc_y": 460, "player_feet": 475, "monster_feet": 465,
                    "loot_y": 490, "player_x": 150, "npc_x0": 350,
                    "monster_x0": 620},
}
DEFAULT_LAYOUT = {"npc_y": 420, "player_feet": 472, "monster_feet": 462,
                  "loot_y": 488, "player_x": 150, "npc_x0": 350,
                  "monster_x0": 600}
# Backwards-compatible ground line (front-row feet) per location.
BASELINE = {loc: v["player_feet"] for loc, v in STAGE_LAYOUT.items()}
DEFAULT_BASELINE = DEFAULT_LAYOUT["player_feet"]

# Sprite box sizes (square <image> box, px in stage space). Humans ~1.8m =
# 150 front / 115 back (perspective); monsters scale with HP/body mass so a
# Giant Rat reads small next to an Ember Drake. Measured content boxes in
# Blender (alpha bbox) confirm visual hierarchy after padding compensation.
PLAYER_SIZE_FIGHT, PLAYER_SIZE_STAND, NPC_SIZE, LOOT_SIZE = 150, 140, 115, 42
MONSTER_SIZE = {
    "Giant Rat": 70, "Forest Wolf": 85, "Road Bandit": 140,
    "Marsh Wraith": 150, "Cave Troll": 190, "Ember Drake": 205,
}
DEFAULT_MONSTER_SIZE = 110
# Bottom transparent padding fraction per sprite (Blender alpha-bbox measure),
# used so the *visible* feet — not the image edge — sit on the ground line.
FOOT_PAD = {
    "player": 0.108, "player_standing": 0.086,
    "Giant Rat": 0.149, "Forest Wolf": 0.165, "Road Bandit": 0.103,
    "Marsh Wraith": 0.058, "Cave Troll": 0.07, "Ember Drake": 0.132,
}
DEFAULT_FOOT_PAD = 0.07
WRAITH_FLOAT = 14  # the wraith hovers instead of standing

LOCATION_TYPE = {
    "riverside_village": "town", "capital_city": "town",
    "oakhollow_forest": "wild", "sunken_marsh": "wild",
    "deep_cave": "dungeon", "ember_ridge": "dungeon",
}


def _esc(value):
    try:
        return html.escape(str(value), quote=True)
    except Exception:
        return "?"


def _file_url(path):
    """file:/// URL for an absolute path (Windows-safe)."""
    try:
        p = os.path.abspath(path).replace("\\", "/")
        if not p.startswith("/"):
            p = "/" + p
        return "file://" + p
    except Exception:
        return ""


def _halo(width=3):
    """Dark outline behind stage <text> so labels read over bright backdrops.

    Uses paint-order:stroke so the stroke never eats the glyph fill.
    Never raises."""
    try:
        w = float(width)
    except Exception:
        w = 3
    return (f'stroke="{INK}" stroke-width="{w}" paint-order="stroke" '
            f'stroke-linejoin="round"')


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


def _http_asset_path(assets_dir, rel):
    """Public /assets/... path for a repo-relative asset, or '' when missing. Never raises."""
    try:
        path = _local_file(assets_dir, rel or "")
        if not path or not os.path.exists(path):
            return ""
        base = os.path.abspath(assets_dir)
        rel_path = os.path.relpath(os.path.abspath(path), base).replace(os.sep, "/")
        if rel_path.startswith(".."):
            return ""
        return "/assets/" + rel_path
    except Exception:
        return ""


def _svg_or_emoji(assets_dir, rel, emoji, size=64, url_mode="file"):
    """Inline art <size>px square (SVG markup or PNG <img>), or a big emoji fallback. Never raises."""
    try:
        path = _local_file(assets_dir, rel or "")
        if path and path.lower().endswith(".png"):
            if url_mode == "http":
                url = _http_asset_path(assets_dir, rel or "")
            else:
                url = _file_url(path)
            if url:
                return (f'<img src="{_esc(url)}" alt="" width="{size}" height="{size}" '
                        f'style="width:{size}px;height:{size}px;object-fit:contain;"/>')
            return (f'<div style="width:{size}px;height:{size}px;font-size:{size // 2}px;'
                    f'display:flex;align-items:center;justify-content:center;">'
                    f'{_esc(emoji or "?")}</div>')
        if path:
            with open(path, encoding="utf-8") as f:
                svg = f.read()
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
        if path.lower().endswith(".png"):
            return None  # PNGs are embedded via <image>, not inlined
        with open(path, encoding="utf-8") as f:
            svg = f.read()
        start = svg.find(">")
        end = svg.find("</svg>")
        if start < 0 or end < 0 or end <= start:
            return None
        return svg[start + 1:end]
    except Exception:
        return None


def _nested_art(assets_dir, rel, x, y, size, ring_color, label="?", url_mode="file"):
    """Place asset artwork on the stage; falls back to a ringed token."""
    try:
        path = _local_file(assets_dir, rel or "")
        if path and path.lower().endswith(".png"):
            if url_mode == "http":
                url = _http_asset_path(assets_dir, rel or "")
            else:
                url = _file_url(path)
            if url:
                return (f'<image href="{_esc(url)}" x="{x}" y="{y}" '
                        f'width="{size}" height="{size}" preserveAspectRatio="xMidYMid meet"/>')
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
            f'fill="{PARCHMENT}" font-weight="bold" {_halo(4)}>'
            f'{_esc((label or "?")[:1])}</text>')


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
                f'font-size="12" fill="{PARCHMENT}" {_halo(2.5)}>'
                f'{_esc(hp)}/{_esc(max_hp)}</text>')
    return out


def _pines(xs, base_y, scale, color, opacity=1.0):
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


class _ViewerHandler(BaseHTTPRequestHandler):
    """Serves shell, state.json and /assets/* from the owning GameViewer. Never raises."""

    def log_message(self, *args):  # quiet: turn loop already logs
        pass

    def do_GET(self):
        try:
            viewer = getattr(self.server, "viewer", None)
            if viewer is None:
                self._send(500, b"no viewer", "text/plain")
                return
            parsed = urllib.parse.urlparse(self.path)
            route = parsed.path or "/"
            if route in ("/", "/index.html"):
                body = viewer.shell_html().encode("utf-8")
                self._send(200, body, "text/html; charset=utf-8", no_store=True)
                return
            if route in ("/state.json", "/state"):
                body = viewer.state_json().encode("utf-8")
                self._send(200, body, "application/json", no_store=True)
                return
            if route.startswith("/assets/"):
                rel = urllib.parse.unquote(route[len("/assets/"):])
                self._serve_asset(viewer, rel)
                return
            self._send(404, b"not found", "text/plain")
        except Exception:
            try:
                self._send(500, b"error", "text/plain")
            except Exception:
                pass

    def _send(self, code, body, ctype, no_store=False):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        if no_store:
            self.send_header("Cache-Control", "no-store")
        else:
            self.send_header("Cache-Control", "public, max-age=3600")
        self.end_headers()
        self.wfile.write(body)

    def _serve_asset(self, viewer, rel):
        try:
            if not rel or ".." in rel.split("/") or rel.startswith("/"):
                self._send(404, b"not found", "text/plain")
                return
            base = os.path.abspath(viewer.assets_dir or "")
            if not base:
                self._send(404, b"not found", "text/plain")
                return
            full = os.path.abspath(os.path.join(base, *rel.split("/")))
            if not full.startswith(base) or not os.path.isfile(full):
                self._send(404, b"not found", "text/plain")
                return
            ctype, _ = mimetypes.guess_type(full)
            with open(full, "rb") as f:
                body = f.read()
            self._send(200, body, ctype or "application/octet-stream")
        except Exception:
            try:
                self._send(404, b"not found", "text/plain")
            except Exception:
                pass


class GameViewer:
    """Serves a live HUD on 127.0.0.1 with in-place updates. Never raises."""

    def __init__(self, assets_dir=None, refresh=1, path="", port=0):
        self.assets_dir = assets_dir
        try:
            self.refresh = max(0.0, float(refresh or 0))
        except Exception:
            self.refresh = 1.0
        if self.refresh and self.refresh < 0.5:
            self.refresh = 0.5
        try:
            self.path = os.path.abspath(path) if path else os.path.join(
                tempfile.gettempdir(), "airealms-viewer.html")
        except Exception:
            self.path = os.path.join(tempfile.gettempdir(), "airealms-viewer.html")
        try:
            root, ext = os.path.splitext(self.path)
            self.state_path = root + "-state.json"
        except Exception:
            self.state_path = self.path + ".json"
        self._opened = False
        self._lock = threading.Lock()
        self._seq = 0
        self._state = self._build_state(0, {}, {}, "", "", [], "starting")
        self._state["seq"] = 0
        self._server = None
        self._thread = None
        self.port = 0
        try:
            self._requested_port = int(port or 0)
        except Exception:
            self._requested_port = 0
        self.start_server()

    # -- server ----------------------------------------------------------
    def start_server(self):
        """Bind 127.0.0.1 (ephemeral port when 0). Never raises."""
        if self._server is not None:
            return
        try:
            srv = ThreadingHTTPServer(("127.0.0.1", self._requested_port), _ViewerHandler)
            srv.viewer = self
            srv.daemon_threads = True
            self._server = srv
            try:
                self.port = srv.server_address[1]
            except Exception:
                self.port = 0
            th = threading.Thread(target=srv.serve_forever, kwargs={"poll_interval": 0.2})
            th.daemon = True
            self._thread = th
            th.start()
        except Exception:
            self._server = None
            self._thread = None
            self.port = 0

    def stop(self):
        """Shut the local server down. Never raises."""
        try:
            if self._server is not None:
                self._server.shutdown()
                self._server.server_close()
        except Exception:
            pass
        self._server = None
        self._thread = None

    @property
    def url(self):
        try:
            if self._server is not None and self.port:
                return f"http://127.0.0.1:{self.port}/"
        except Exception:
            pass
        return ""

    def open(self):
        """Pop the browser once (server URL preferred, file fallback). Never raises."""
        if self._opened:
            return
        self._opened = True
        try:
            if os.getenv("AIREALMS_NO_BROWSER", "").lower() in ("1", "true", "yes", "on"):
                return
            import webbrowser
            target = self.url
            if not target:
                target = f"file:///{self.path.replace(os.sep, '/')}"
            webbrowser.open(target)
        except Exception:
            pass

    def update(self, turn=0, me=None, here=None, action_desc="",
               result_narrative="", log=None, status="playing"):
        """Publish one frame: memory + state.json + file snapshot. Never raises."""
        try:
            state = self._build_state(turn, me or {}, here or {},
                                      action_desc, result_narrative, log or [], status)
            with self._lock:
                self._seq += 1
                state["seq"] = self._seq
                # Carry forward last-known HUD values: some frames are partial
                # (e.g. GET /status carries no `kills` — only the per-action
                # player snapshot does), so never blank a known number to "?".
                prev = self._state or {}
                for k in ("name", "level", "hp", "max_hp", "gold", "kills"):
                    if state.get(k) in ("?", None) and prev.get(k) not in ("?", None):
                        state[k] = prev[k]
                self._state = state
                carried = {k: state[k] for k in
                           ("name", "level", "hp", "max_hp", "gold", "kills")
                           if k in state}
            # Sidecar for debugging / headless runs.
            try:
                tmp = self.state_path + ".tmp"
                with open(tmp, "w", encoding="utf-8", newline="\n") as f:
                    json.dump(state, f)
                os.replace(tmp, self.state_path)
            except Exception:
                pass
            # File snapshot keeps the legacy meta-refresh fallback when the
            # local server cannot bind (browser opened on file://).
            try:
                page = self._render(turn, me or {}, here or {},
                                    action_desc, result_narrative, log or [], status,
                                    _fallback=carried)
                tmp = self.path + ".tmp"
                with open(tmp, "w", encoding="utf-8", newline="\n") as f:
                    f.write(page)
                os.replace(tmp, self.path)
            except Exception:
                pass
        except Exception:
            pass

    def state_json(self):
        """Current state payload as JSON. Never raises."""
        try:
            with self._lock:
                state = dict(self._state)
            return json.dumps(state)
        except Exception:
            return "{}"

    def shell_html(self):
        """Static shell served once; JS patches it via state.json. Never raises."""
        try:
            poll = self.refresh if self.refresh else 0
            poll_js = "0" if not poll else repr(float(poll))
            with self._lock:
                initial = dict(self._state)
            return self._render_shell(initial, poll_js)
        except Exception:
            return "<html><body>viewer unavailable</body></html>"

    # -- stage ---------------------------------------------------------
    def background_url(self, loc_id):
        """file:// URL of the Blender-rendered backdrop, or '' when missing."""
        try:
            if not (self.assets_dir and loc_id):
                return ""
            path = os.path.join(self.assets_dir, "backgrounds", f"{loc_id}.png")
            return _file_url(path) if os.path.exists(path) else ""
        except Exception:
            return ""

    def background_http_path(self, loc_id):
        """/assets/... path of the Blender-rendered backdrop, or '' when missing."""
        try:
            if not (self.assets_dir and loc_id):
                return ""
            rel = f"backgrounds/{loc_id}.png"
            return _http_asset_path(self.assets_dir, rel)
        except Exception:
            return ""

    @staticmethod
    def _split(me_raw, here_raw):
        try:
            me = me_raw.get("data", me_raw) if isinstance(me_raw, dict) else {}
            world = here_raw.get("data", here_raw) if isinstance(here_raw, dict) else {}
            if not isinstance(me, dict):
                me, world = {}, {}
            if not isinstance(world, dict):
                world = {}
            return me, world
        except Exception:
            return {}, {}

    def _pack_html(self, me, url_mode="file"):
        try:
            inv = [i for i in (me.get("inventory", []) or []) if isinstance(i, dict)][:10]
            rows = []
            for i in inv:
                art = _svg_or_emoji(self.assets_dir,
                                    i.get("asset") or _expected("item", i.get("item_id", "")),
                                    "?", size=32, url_mode=url_mode)
                star = " ⭐" if i.get("equipped") else ""
                rows.append(
                    f'<div style="display:flex;gap:8px;align-items:center;padding:3px 0;">{art}'
                    f'<span style="color:{PARCHMENT};font-size:13px;">{_esc(i.get("name", "?"))} '
                    f'x{_esc(i.get("qty", 1))}{star}</span></div>')
            return "".join(rows) if rows else f'<div style="color:{SLATE};">Empty pack.</div>'
        except Exception:
            return f'<div style="color:{SLATE};">Empty pack.</div>'

    def _quests_html(self, me):
        try:
            quests = [q for q in (me.get("active_quests", []) or []) if isinstance(q, dict)][:6]
            return "".join(
                f'<div style="padding:3px 0;font-size:13px;color:{PARCHMENT};">'
                f'⚔ {_esc(q.get("title", "?"))} — {_esc(q.get("progress", "?"))}</div>'
                for q in quests) or f'<div style="color:{SLATE};">No active quests.</div>'
        except Exception:
            return f'<div style="color:{SLATE};">No active quests.</div>'

    def _exits_html(self, world):
        try:
            exits = [e.get("to", "?") for e in (world.get("exits", []) or []) if isinstance(e, dict)]
            return " ".join(
                f'<span style="background:{PANEL};border:1px solid {GOLD};color:{GOLD};'
                f'border-radius:12px;padding:2px 10px;margin:2px;font-size:12px;">{_esc(e)}</span>'
                for e in exits) or f'<span style="color:{SLATE};">no exits</span>'
        except Exception:
            return f'<span style="color:{SLATE};">no exits</span>'

    def _build_state(self, turn, me_raw, here_raw, action_desc, result_narrative, log, status):
        """JSON-serializable frame for state.json + live patching. Never raises."""
        try:
            me, world = self._split(me_raw, here_raw)
            loc_id = world.get("location_id") or me.get("location", "?")
            loc_type = world.get("type")
            if loc_type not in ("town", "wild", "dungeon"):
                loc_type = LOCATION_TYPE.get(loc_id)
            baseline = BASELINE.get(loc_id, DEFAULT_BASELINE)
            backdrop = self.background_http_path(loc_id)
            tokens = self._tokens_svg(me, world, loc_id, loc_type, baseline, "http")
            terrain = ""
            if not backdrop:
                try:
                    terrain = (f'<svg viewBox="0 0 {STAGE_W} {STAGE_H}" '
                               f'style="width:100%;height:100%;display:block;">'
                               f'{self._terrain_svg(loc_id, loc_type, baseline)}</svg>')
                except Exception:
                    terrain = ""
            try:
                log_list = [str(e) for e in list(log or [])[-12:]]
            except Exception:
                log_list = []
            try:
                dead = status == "dead" or me.get("alive") is False
            except Exception:
                dead = status == "dead"
            return {
                "turn": turn, "seq": 0, "status": status or "playing",
                "name": me.get("name", "?"), "level": me.get("level", "?"),
                "hp": me.get("hp", "?"), "max_hp": me.get("max_hp", "?"),
                "gold": me.get("gold", "?"), "kills": me.get("kills", "?"),
                "loc_id": loc_id, "loc_type": loc_type or "?",
                "backdrop": backdrop, "tokens_svg": tokens, "terrain_svg": terrain,
                "description": world.get("description", "") or "",
                "exits_html": self._exits_html(world),
                "pack_html": self._pack_html(me, "http"),
                "quests_html": self._quests_html(me),
                "action_desc": action_desc or "", "result_narrative": result_narrative or "",
                "log": log_list, "dead": dead,
            }
        except Exception:
            return {"turn": turn or 0, "seq": 0, "status": "playing", "log": []}

    def _render_shell(self, initial, poll_js):
        """Static shell: backdrop double-buffer crossfades, tokens/HUD patch in place."""
        try:
            init = initial or {}
            backdrop = init.get("backdrop", "") or ""
            tokens = init.get("tokens_svg", "") or ""
            terrain = init.get("terrain_svg", "") or ""
            name = _esc(init.get("name", "?"))
            polling_note = (f"live · polls every {self.refresh:g}s" if self.refresh
                            else "paused · refresh with ?poll=0")
            return (
                "<!DOCTYPE html><html><head><meta charset='utf-8'>"
                f"<title>AI Realms — {name} (live)</title>"
                "<style>"
                "html{background:#12141C;}"
                ".bg-layer{position:absolute;inset:0;width:100%;height:100%;"
                "object-fit:cover;transition:opacity .45s ease;}"
                ".bg-visible{opacity:1;}.bg-hidden{opacity:0;}"
                ".hpwrap{background:#0B0D13;border:1px solid #2C3244;border-radius:4px;"
                "width:120px;height:10px;}"
                "#hpfill{height:8px;border-radius:3px;transition:width .6s ease,background .6s ease;}"
                "#tokens{transition:opacity .25s ease;}"
                "</style></head>"
                f'<body style="background:{INK};color:{PARCHMENT};font-family:system-ui,sans-serif;margin:0;">'
                f'<div id="banner" style="display:none;background:{BLOOD};color:#fff;'
                'text-align:center;padding:8px;font-weight:bold;">'
                '☠ YOU DIED — see the CLI debrief ☠</div>'
                f'<div style="padding:12px 16px;border-bottom:1px solid #2C3244;display:flex;'
                'gap:16px;align-items:center;flex-wrap:wrap;">'
                '<div style="font-family:Georgia,serif;font-size:22px;">⚔ AI Realms</div>'
                f'<div style="font-size:20px;"><span id="hname">{name}</span> '
                f'<span style="color:{GOLD};">Lv <span id="hlevel">{_esc(init.get("level", "?"))}</span></span></div>'
                '<div><div class="hpwrap"><div id="hpfill" style="width:0"></div></div>'
                f'<div id="hptext" style="font-size:11px;color:{SLATE};">?</div></div>'
                f'<div>🪙 <span id="hgold">{_esc(init.get("gold", "?"))}</span> gold</div>'
                f'<div>💀 <span id="hkills">{_esc(init.get("kills", "?"))}</span> kills</div>'
                f'<div id="hmeta" style="color:{SLATE};">turn {_esc(init.get("turn", 0))} · '
                f'{_esc(init.get("status", "playing"))}</div>'
                f'<div style="color:{SLATE};font-size:12px;" id="hpoll">{_esc(polling_note)}</div>'
                '</div>'
                '<div style="padding:12px 16px 0;">'
                f'<div style="background:{PANEL};border:1px solid #2C3244;border-radius:10px;padding:12px;">'
                '<div id="stage" style="position:relative;border-radius:10px;overflow:hidden;aspect-ratio:16/9;'
                f'background:{INK};">'
                f'<img id="bgA" class="bg-layer bg-visible" alt="" src="{_esc(backdrop)}"'
                f' style="display:{ "block" if backdrop else "none"};"/>'
                '<img id="bgB" class="bg-layer bg-hidden" alt="" src="" style="display:block;"/>'
                f'<div id="terrain" style="position:absolute;inset:0;">{terrain}</div>'
                f'<svg id="tokens" viewBox="0 0 {STAGE_W} {STAGE_H}" preserveAspectRatio="xMidYMid meet" '
                'style="position:absolute;inset:0;width:100%;height:100%;">' + tokens + '</svg>'
                '</div>'
                f'<div id="hdesc" style="font-size:13px;color:{SLATE};margin-top:8px;">'
                f'{_esc(init.get("description", ""))}</div>'
                f'<div id="hexits" style="margin-top:6px;">{init.get("exits_html", "")}</div>'
                '</div></div>'
                '<div style="display:flex;gap:12px;padding:12px 16px;flex-wrap:wrap;">'
                f'<div style="flex:1;min-width:240px;background:{PANEL};border:1px solid #2C3244;'
                'border-radius:10px;padding:12px;">'
                f'<div style="font-size:12px;color:{SLATE};">PACK</div>'
                f'<div id="hpack">{init.get("pack_html", "")}</div>'
                f'<div style="font-size:12px;color:{SLATE};margin-top:8px;">QUESTS</div>'
                f'<div id="hquests">{init.get("quests_html", "")}</div>'
                '</div>'
                f'<div style="flex:2;min-width:300px;background:{PANEL};border:1px solid #2C3244;'
                'border-radius:10px;padding:12px;">'
                f'<div style="font-size:12px;color:{SLATE};">LAST ACTION</div>'
                f'<div id="hact" style="font-size:13px;">{_esc(init.get("action_desc", "") or "—")}</div>'
                f'<div id="hres" style="font-size:13px;color:{VERDIGRIS};">'
                f'{_esc(init.get("result_narrative", ""))}</div>'
                f'<div style="font-size:12px;color:{SLATE};margin-top:8px;">ADVENTURE LOG</div>'
                '<div id="hlog"></div>'
                '</div></div>'
                '<script>'
                f'const POLL_S = {poll_js};'
                'let lastTurn = ' + repr(int(init.get("turn", 0) or 0)) + ';'
                'let lastSeq = ' + repr(int(init.get("seq", 0) or 0)) + ';'
                'let lastTokens = null;'
                'let showingA = true;'
                'const $ = (id) => document.getElementById(id);'
                'function hpColor(hp, mx){'
                '  try{ const p = Number(hp)/Number(mx||1);'
                '    if(p>0.5) return "' + VERDIGRIS + '";'
                '    if(p>0.25) return "' + GOLD + '";'
                '    return "' + BLOOD + '";'
                '  }catch(e){ return "' + SLATE + '"; } }'
                'function setBackdrop(url){'
                '  const front = showingA ? $("bgA") : $("bgB");'
                '  const back = showingA ? $("bgB") : $("bgA");'
                '  const cur = front.getAttribute("src") || "";'
                '  if((url||"") === cur && front.style.display !== "none") return;'
                '  if(!url){ front.style.display = "none"; $("terrain").style.display = "block"; return; }'
                '  const pre = new Image();'
                '  pre.onload = () => {'
                '    back.src = url; back.style.display = "block";'
                '    back.classList.remove("bg-hidden"); back.classList.add("bg-visible");'
                '    front.classList.remove("bg-visible"); front.classList.add("bg-hidden");'
                '    showingA = !showingA; $("terrain").style.display = "none"; };'
                '  pre.onerror = () => { front.style.display = "none"; $("terrain").style.display = "block"; };'
                '  pre.src = url; }'
                'function applyState(s){'
                '  if(!s || typeof s !== "object") return;'
                '  if(typeof s.seq === "number"){ if(s.seq === lastSeq) return; lastSeq = s.seq; }'
                '  else if(typeof s.turn === "number" && s.turn === lastTurn) return;'
                '  if(typeof s.turn === "number") lastTurn = s.turn;'
                '  try{ document.title = "AI Realms — " + (s.name||"?") + " @ " + (s.loc_id||"?"); }catch(e){}'
                '  try{ $("hname").textContent = s.name ?? "?"; }catch(e){}'
                '  try{ $("hlevel").textContent = s.level ?? "?"; }catch(e){}'
                '  try{ $("hgold").textContent = s.gold ?? "?"; }catch(e){}'
                '  try{ $("hkills").textContent = s.kills ?? "?"; }catch(e){}'
                '  try{ $("hmeta").textContent = "turn " + (s.turn ?? "?") + " · " + (s.status || ""); }catch(e){}'
                '  try{'
                '    const hp = Number(s.hp), mx = Number(s.max_hp);'
                '    if(isFinite(hp) && isFinite(mx) && mx > 0){'
                '      const pct = Math.max(0, Math.min(1, hp/mx));'
                '      const fill = $("hpfill");'
                '      fill.style.width = Math.round(pct*100) + "%";'
                '      fill.style.background = hpColor(hp, mx);'
                '      $("hptext").textContent = s.hp + "/" + s.max_hp;'
                '    } else { $("hptext").textContent = (s.hp ?? "?") + "/" + (s.max_hp ?? "?"); }'
                '  }catch(e){}'
                '  try{ setBackdrop(s.backdrop || ""); }catch(e){}'
                '  try{'
                '    if(s.backdrop){ $("terrain").style.display = "none"; }'
                '    else if(s.terrain_svg){ $("terrain").innerHTML = s.terrain_svg;'
                '      $("terrain").style.display = "block"; }'
                '  }catch(e){}'
                '  try{'
                '    const tok = $("tokens");'
                '    if(typeof s.tokens_svg === "string" && s.tokens_svg !== lastTokens){'
                '      lastTokens = s.tokens_svg;'
                '      tok.style.opacity = "0";'
                '      requestAnimationFrame(() => { tok.innerHTML = s.tokens_svg; tok.style.opacity = "1"; });'
                '    }'
                '  }catch(e){}'
                '  try{ $("hdesc").textContent = s.description || ""; }catch(e){}'
                '  try{ if(typeof s.exits_html === "string") $("hexits").innerHTML = s.exits_html; }catch(e){}'
                '  try{ if(typeof s.pack_html === "string") $("hpack").innerHTML = s.pack_html; }catch(e){}'
                '  try{ if(typeof s.quests_html === "string") $("hquests").innerHTML = s.quests_html; }catch(e){}'
                '  try{ $("hact").textContent = s.action_desc || "—"; }catch(e){}'
                '  try{ $("hres").textContent = s.result_narrative || ""; }catch(e){}'
                '  try{'
                '    const log = Array.isArray(s.log) ? s.log.slice(-12).reverse() : [];'
                '    $("hlog").innerHTML = log.length ? log.map((e) => '
                '      `<div style="padding:4px 0;border-bottom:1px solid #2C3244;font-size:13px;">${String(e).replace(/&/g,"&amp;").replace(/</g,"&lt;")}</div>`'
                '    ).join("") : `<div style="color:' + SLATE + ';">Log is empty.</div>`;'
                '  }catch(e){}'
                '  try{ $("banner").style.display = s.dead ? "block" : "none"; }catch(e){}'
                '}'
                'async function poll(){'
                '  try{ const r = await fetch("state.json?since=" + lastTurn, {cache:"no-store"});'
                '    if(r.ok){ applyState(await r.json()); }'
                '  }catch(e){}'
                '}'
                'try{'
                '  const initLog = ' + json.dumps(list((init.get("log") or []))[-12:][::-1]).replace("</", "<\\/") + ';'
                '  if(Array.isArray(initLog)){'
                '    $("hlog").innerHTML = initLog.length ? initLog.map((e) => '
                '      `<div style="padding:4px 0;border-bottom:1px solid #2C3244;font-size:13px;">${String(e).replace(/&/g,"&amp;").replace(/</g,"&lt;")}</div>`'
                '    ).join("") : ""; }'
                '  $("banner").style.display = ' + ("true" if init.get("dead") else "false") + ' ? "block" : "none";'
                '  if(' + repr(bool(backdrop)) + '){ $("terrain").style.display = "none"; }'
                '}catch(e){}'
                'if(POLL_S > 0){ setInterval(poll, Math.max(500, POLL_S*1000)); poll(); }'
                '</script></body></html>'
            )
        except Exception:
            return "<html><body>viewer unavailable</body></html>"

    def _terrain_svg(self, loc_id, loc_type, baseline):
        """Drawn backdrop (used when there is no Blender background PNG)."""
        sky = SKY.get(loc_type, "#181C28")
        ground = GROUND.get(loc_type, "#12141C")
        decor = DECOR.get(loc_type, SLATE)
        parts = [f'<rect x="0" y="0" width="{STAGE_W}" height="{STAGE_H}" rx="10" fill="{sky}"/>']

        if loc_type == "wild":
            parts.append(_pines([30, 110, 830, 890], baseline - 60, 1.1, VERDIGRIS, 0.9))
            parts.append(_pines([180, 760], baseline - 60, 0.7, VERDIGRIS, 0.5))
        elif loc_type == "town":
            parts.append(
                f'<g opacity="0.85" stroke="{GOLD}" fill="{INK}" stroke-width="3">'
                f'<polygon points="770,{baseline - 150} 850,{baseline - 200} 930,{baseline - 150}"/>'
                f'<rect x="785" y="{baseline - 150}" width="130" height="90"/>'
                f'<rect x="835" y="{baseline - 110}" width="30" height="50" fill="{GOLD}"/>'
                f'<polygon points="60,{baseline - 120} 120,{baseline - 160} 180,{baseline - 120}"/>'
                f'<rect x="72" y="{baseline - 120}" width="96" height="60"/>'
                f'</g>')
        elif loc_type == "dungeon":
            parts.append(
                f'<ellipse cx="700" cy="20" rx="260" ry="70" fill="{BLOOD}" opacity="0.18"/>'
                f'<g fill="{HAIRLINE}">'
                f'<polygon points="80,0 100,0 90,46"/><polygon points="420,0 444,0 432,58"/>'
                f'<polygon points="700,0 720,0 710,44"/><polygon points="880,0 898,0 889,40"/>'
                f'</g>')
        else:
            parts.append(_pines([40, 880], baseline - 60, 0.9, SLATE, 0.6))

        # road across the scene + ground strip down to the baseline
        parts.append(
            f'<polygon points="40,{STAGE_H} 470,0 610,0 180,{STAGE_H}" '
            f'fill="{HAIRLINE}" opacity="0.5"/>')
        parts.append(f'<rect x="0" y="{baseline}" width="{STAGE_W}" '
                     f'height="{STAGE_H - baseline}" fill="{ground}"/>')
        return "".join(parts)

    def _place(self, cx, feet_y, size, pad=DEFAULT_FOOT_PAD, float_px=0):
        """Top-left y for an <image> box so visible feet rest on feet_y."""
        y = feet_y - size + size * pad - float_px
        return cx - size / 2, y

    def _shadow(self, cx, feet_y, w):
        return (f'<ellipse cx="{cx}" cy="{feet_y + 4}" rx="{w / 2}" ry="7" '
                f'fill="#000000" opacity="0.35"/>')

    def _tokens_svg(self, me, world, loc_id, loc_type, baseline, url_mode="file"):
        """Character, monsters, loot, NPCs and labels, in stage coordinates."""
        ad = self.assets_dir
        decor = DECOR.get(loc_type, SLATE)
        lay = STAGE_LAYOUT.get(loc_id, DEFAULT_LAYOUT)
        npc_y = lay["npc_y"]
        player_feet = lay["player_feet"]
        monster_feet = lay["monster_feet"]
        loot_y = lay["loot_y"]
        parts = []

        # NPCs: back row, human scale with perspective (~0.77x player).
        npcs = [n for n in (world.get("npcs", []) or []) if isinstance(n, dict)][:4]
        for i, n in enumerate(npcs):
            cx = lay["npc_x0"] + i * 120
            x, y = self._place(cx, npc_y, NPC_SIZE)
            parts.append(self._shadow(cx, npc_y, NPC_SIZE * 0.55))
            parts.append(_nested_art(ad, n.get("asset") or _expected("npc", n.get("npc_id", "")),
                                     x, y, NPC_SIZE, VERDIGRIS, n.get("name", "?"), url_mode))
            parts.append(f'<text x="{cx}" y="{y - 8}" text-anchor="middle" font-size="13" '
                         f'fill="{PARCHMENT}" {_halo(2.5)}>{_esc(n.get("name", "?"))}</text>')

        # The character, front row: fighting stance in combat, relaxed pose
        # when no monsters are around.
        name = me.get("name", "?") if isinstance(me, dict) else "?"
        cx = lay["player_x"]
        fighting = bool([m for m in (world.get("monsters", []) or []) if isinstance(m, dict)])
        psize = PLAYER_SIZE_FIGHT if fighting else PLAYER_SIZE_STAND
        ppad = FOOT_PAD.get("player" if fighting else "player_standing", DEFAULT_FOOT_PAD)
        px, py = self._place(cx, player_feet, psize, ppad)
        parts.append(f'<text x="{cx}" y="{py - 40}" text-anchor="middle" font-size="14" '
                     f'fill="{GOLD}" font-weight="bold" {_halo(3)}>'
                     f'{_esc(name)} · Lv {_esc(me.get("level", "?"))}</text>')
        parts.append(_svg_bar(cx - 50, py - 32, 100,
                              me.get("hp", 0), me.get("max_hp", 0)))
        parts.append(self._shadow(cx, player_feet, psize * 0.5))
        parts.append(_nested_art(ad, me.get("asset") or _expected("player", "fighting" if fighting else "standing"),
                                 px, py, psize, GOLD, name, url_mode))

        # Monsters: front row, feet on their ground line, size by species.
        mons = [m for m in (world.get("monsters", []) or []) if isinstance(m, dict)]
        shown = mons[:4]
        for i, m in enumerate(shown):
            mname = m.get("name", "?")
            size = MONSTER_SIZE.get(mname, DEFAULT_MONSTER_SIZE)
            pad = FOOT_PAD.get(mname, DEFAULT_FOOT_PAD)
            flot = WRAITH_FLOAT if mname == "Marsh Wraith" else 0
            cxm = lay["monster_x0"] + i * (size + 45)
            xm, ym = self._place(cxm, monster_feet, size, pad, flot)
            parts.append(f'<text x="{cxm}" y="{ym - 36}" text-anchor="middle" '
                         f'font-size="13" fill="{PARCHMENT}" {_halo(2.5)}>{_esc(mname)}</text>')
            parts.append(_svg_bar(cxm - 40, ym - 30, 80, m.get("hp", 0), m.get("max_hp", 0)))
            parts.append(self._shadow(cxm, monster_feet, size * 0.6))
            parts.append(_nested_art(ad, m.get("asset") or _expected("monster", mname),
                                     xm, ym, size, BLOOD, mname, url_mode))
            if (m.get("drops") or {}).get("name"):
                parts.append(f'<circle cx="{xm + size - 6}" cy="{ym + 10}" r="7" fill="{GOLD}">'
                             f'<title>{_esc(m["drops"]["name"])}</title></circle>')
        if len(mons) > len(shown):
            parts.append(f'<text x="920" y="{monster_feet - 130}" text-anchor="middle" font-size="14" '
                         f'fill="{SLATE}" {_halo(2.5)}>+{len(mons) - len(shown)} more</text>')
        if not mons:
            parts.append(f'<text x="640" y="{monster_feet - 60}" text-anchor="middle" font-size="15" '
                         f'fill="{SLATE}" {_halo(3)}>No monsters — safe to rest.</text>')

        # Loot lying on the ground line.
        loot = [g for g in (world.get("items_on_ground", []) or []) if isinstance(g, dict)][:4]
        for i, g in enumerate(loot):
            cxg = 330 + i * 90
            xg, yg = self._place(cxg, loot_y, LOOT_SIZE, 0.1)
            parts.append(self._shadow(cxg, loot_y, LOOT_SIZE * 0.7))
            parts.append(_nested_art(ad, g.get("asset") or _expected("item", g.get("item_id", "")),
                                     xg, yg, LOOT_SIZE, GOLD, g.get("name", "?"), url_mode))
            qty = f' x{g.get("qty", 1)}' if g.get("qty", 1) != 1 else ""
            parts.append(f'<text x="{cxg}" y="{yg - 6}" text-anchor="middle" font-size="12" '
                         f'fill="{GOLD}" {_halo(2.5)}>{_esc(g.get("name", "?"))}{_esc(qty)}</text>')

        # Caption
        parts.append(f'<text x="16" y="34" font-size="24" fill="{PARCHMENT}" '
                     f'font-family="Georgia,serif" {_halo(4)}>{_esc(loc_id)}</text>')
        parts.append(f'<text x="{STAGE_W - 16}" y="34" font-size="13" fill="{decor}" '
                     f'text-anchor="end" {_halo(2.5)}>{_esc(loc_type or "?")}</text>')
        return "".join(parts)

    def _stage(self, me, world, loc_id, loc_type):
        baseline = BASELINE.get(loc_id, DEFAULT_BASELINE)
        tokens = self._tokens_svg(me, world, loc_id, loc_type, baseline)
        bg = self.background_url(loc_id)
        if bg:
            # Backdrop PNG is 2848x1600 (1.78) == 960x540 stage, so the SVG
            # overlay maps 1:1 with preserveAspectRatio="xMidYMid meet".
            return (
                f'<div style="position:relative;border-radius:10px;overflow:hidden;aspect-ratio:16/9;">'
                f'<img src="{_esc(bg)}" alt="{_esc(loc_id)}" '
                f'style="width:100%;height:100%;object-fit:cover;display:block;"/>'
                f'<svg viewBox="0 0 {STAGE_W} {STAGE_H}" preserveAspectRatio="xMidYMid meet" '
                f'style="position:absolute;inset:0;width:100%;height:100%;">{tokens}</svg>'
                f'</div>')
        return (f'<svg viewBox="0 0 {STAGE_W} {STAGE_H}" '
                f'style="width:100%;height:auto;display:block;">'
                f'{self._terrain_svg(loc_id, loc_type, baseline)}{tokens}</svg>')

    def _render(self, turn, me_raw, here_raw, action_desc, result_narrative, log, status,
                _fallback=None):
        me = me_raw.get("data", me_raw) if isinstance(me_raw, dict) else {}
        world = here_raw.get("data", here_raw) if isinstance(here_raw, dict) else {}
        if not isinstance(me, dict):
            me, world = {}, {}
        if not isinstance(world, dict):
            world = {}
        if isinstance(_fallback, dict) and isinstance(me, dict):
            # Same carry-forward as the live state: never blank a known
            # HUD number (e.g. kills, which GET /status does not return).
            me = dict(me)
            for k, v in _fallback.items():
                if me.get(k) in ("?", None) and v not in ("?", None):
                    me[k] = v

        name = me.get("name", "?")
        level = me.get("level", "?")
        hp, max_hp = me.get("hp", "?"), me.get("max_hp", "?")
        gold = me.get("gold", "?")
        kills = me.get("kills", "?")
        loc_id = world.get("location_id") or me.get("location", "?")
        loc_type = world.get("type")
        if loc_type not in ("town", "wild", "dungeon"):
            loc_type = LOCATION_TYPE.get(loc_id)

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
