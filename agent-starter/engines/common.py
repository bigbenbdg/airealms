"""Shared infra for the reference agent: .env loading, HTTP, skill URL, param mirror."""
import json
import os
import urllib.request
from pathlib import Path


def _load_dotenv():
    """Minimal .env loader (stdlib-only): repo root, cwd, and script dir. Real env wins."""
    here = Path(__file__).resolve().parent.parent
    for cand in (here.parent / ".env", Path.cwd() / ".env", here / ".env"):
        try:
            text = cand.read_text(encoding="utf-8")
        except OSError:
            continue
        for line in text.splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            k, v = k.strip(), v.strip().strip("'\"")
            os.environ.setdefault(k, v)


SKILL_URL_TMPL = "{base}/meta/skill"

# Mirror of the server's REQUIRED_PARAMS (engine.py): checked client-side so
# a malformed LLM choice falls back to the heuristic instead of bouncing.
CLIENT_REQUIRED = {
    "move": ["to"],
    "scout": ["to"],
    "attack": ["target_id"],
    "use_item": ["item_id"],
    "equip_item": ["item_id"],
    "pick_up": ["item_id"],
    "talk_to_npc": ["npc_id"],
    "accept_quest": ["quest_id"],
    "turn_in_quest": ["quest_id"],
    "say": ["message"],
}


def req(method, url, body=None, api_key=None):
    data = json.dumps(body).encode() if body is not None else None
    r = urllib.request.Request(url, data=data, method=method,
                               headers={"Content-Type": "application/json"})
    if api_key:
        r.add_header("Authorization", f"Bearer {api_key}")
    try:
        with urllib.request.urlopen(r, timeout=15) as resp:
            return json.loads(resp.read().decode())
    except Exception as e:
        # surface server envelope on HTTPError
        try:
            payload = e.read().decode()
            print("SERVER:", payload)
        except Exception:
            pass
        raise


def _print_debrief(me):
    """Surface the server's death_report so the operator (or next prompt) learns."""
    rep = me.get("death_report") or {}
    print(f"Dead — slain by {rep.get('killed_by', 'unknown')}.")
    for lesson in (rep.get("lessons") or [])[:3]:
        print("  Lesson:", lesson)
    if rep.get("retry_guidance"):
        print("  Next life:", rep["retry_guidance"])
