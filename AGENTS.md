# AGENTS.md — AI Realms

Guidance for AI coding agents (and humans) working in this repository.

## Project

AI Realms is a persistent multiplayer RPG where **AI agents play characters**
over a plain HTTP/WebSocket API and humans (or other agents) spectate live.
The game is also the benchmark: public progress doubles as a leaderboard of
which model plays smartest.

- Backend: Python **FastAPI** + SQLAlchemy (SQLite by default, Postgres via `DATABASE_URL`).
- Spectator: **React/Vite** SPA, pure SVG graphics, read-only public endpoints.
- Reference agent: stdlib-only `agent-starter/play.py` (OpenAI-compatible brain + heuristic).
- Docs: `01-project-plan.md` (design/rules), `02-api-spec.md` (API contract),
  `03-SKILLS.md` (player handbook), `04-spectator-frontend.md` (UI).

## Repo layout

```
backend/             FastAPI game server
  app/main.py        all endpoints            app/engine.py  rules, cooldowns, respawn, drops
  app/seed.py        world, NPCs, quests      app/goals.py   objectives, death debriefs
  app/models.py      SQLAlchemy models        app/db.py      SQLite→Postgres, ensure_schema()
  tests/test_api.py  20 pytest tests
frontend/            spectator SPA (src/App.jsx, src/api.js)
agent-starter/       reference LLM agent (play.py, engines/{llm,heuristic,assets,viewer}.py)
assets/              generated game art: 42 SVGs + manifest.json + backgrounds/*.png (Blender)
scripts/ship.ps1     test → commit → push helper
.github/             CI workflow, issue/PR templates
```

## Commands

```powershell
# backend
pip install -r backend/requirements.txt
uvicorn app.main:app --app-dir backend --reload --port 8000   # server on :8000

# tests (MUST pass — 37 tests)
pytest backend/tests -q

# frontend
cd frontend; npm ci; npm run dev      # spectator on :5173
npm run build                          # production build

# agent (heuristic unless AIREALMS_LLM_BASE + AIREALMS_LLM_KEY are set)
python agent-starter/play.py --name "Sir Reginald Bot" --turns 5
python agent-starter/play.py --no-llm --turns 5 --view   # live browser game HUD

# art (SVGs are stdlib; backgrounds need Blender + Pillow)
python scripts/make_assets.py          # 42 sprites + manifest.json
python scripts/make_assets.py --check   # CI-safe presence check
blender --background --python scripts/make_backgrounds.py   # 6 map backdrops
python scripts/optimize_backgrounds.py                      # shrink PNGs

# ship (tests → commit → push in one step)
powershell -File scripts/ship.ps1 "commit message"
# NOTE: use "-File" — `powershell scripts/ship.ps1 "msg with, commas"`
```

## Conventions

- **Config** lives in repo-root `.env` (gitignored; see `.env.example`).
  Never commit secrets, `.env`, `*.db`, `node_modules/`, `frontend/dist/`,
  `__pycache__/`, `.pytest_cache/`. Use `os.getenv("VAR", default)` in code;
  `.env` loading is handled in `backend/app/db.py` and `agent-starter/play.py`.
- **SQLite-first**: `models.py` uses Text JSON columns — keep every shape
  JSON-serializable so the code maps to Postgres JSONB unchanged.
- **Schema**: new nullable columns must be added in
  `backend/app/db.py::ensure_schema()` (create_all never alters existing tables).
- **Tests**: every rules/API change needs a test in
  `backend/tests/test_api.py`. Rate-limit/cooldown state is in-memory in
  `app/engine.py`; `fresh_client()` clears it between tests.
- **Authoritative server**: clients never mutate state; cooldowns and
  randomness are server-side. Actions are atomic (`POST /actions`).
- **Envelope**: every response is `{ok, narrative, data, server_time}`; errors
  are `{ok: false, error: {code, message[, retry_after_seconds]}}`. Plain-English
  `narrative` + structured fields, always. IDs are canonical short codes
  (`agt_`, `mon_`, `npc_`, `q_`, `itm_`).
- **Docs sync**: any behavior/API change updates the matching `01–04 *.md`.

## Workflow — keep GitHub updated

This repository lives in lockstep with GitHub. Every finished change must land
**on the remote**, not stay local:

1. Write code + tests.
2. Verify: `pytest backend/tests -q` (and `npm run build` if frontend touched).
3. Commit with a small, descriptive message.
4. Push to `origin/main`.

Use `scripts/ship.ps1` for the loop (tests → stage → commit → push), or:
```
git add -A
git commit -m "summary of the change"
git push origin main
```

Use GitHub properly:
- **Issues**: bug reports / feature requests go through the templates in
  `.github/ISSUE_TEMPLATE/`; reference them from commits (`Fixes #123`).
- **Pull requests**: use `.github/PULL_REQUEST_TEMPLATE.md`; keep CI green;
  big changes get feature branches merged via PR, small ones go straight to main.
- **CI**: `.github/workflows/ci.yml` runs backend tests + frontend build on
  every push/PR — never merge red.
- Branch protection (require CI + reviews on `main`) can be enabled in the
  repo Settings once a maintainer wants it.