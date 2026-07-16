# Sylo — architecture notes for Claude

Self-contained syslog recorder. Three independent, separately-deployable
processes sharing only on-disk state (text files + SQLite), never talking to
each other over a socket or IPC. See [README.md](README.md) for
build/run/setup instructions — this file is about how the code fits
together.

## The three processes

- **`sylo/receiver`** — asyncio UDP/TCP 514 listener (`server.py`). One
  `asyncio.Queue` + writer coroutine per device, **keyed by source IP**
  (never the parsed hostname — spoofable). Writes never touch the event
  loop directly; a small shared `ThreadPoolExecutor` does the blocking
  file I/O (`device_writer.py`). Raw messages land in daily per-device text
  files (source of truth); the parsed form is also handed off to an
  **embedded indexer** (`sylo/indexer`, its own asyncio task/queue inside
  this same process — not a separate process, see `main.py::_start_with_retry`
  for the retry-on-bind-failure loop and `health.py` for the
  `receiver_status.json` file it writes for the webapp to read). Never
  raises into the ingest path — malformed input always falls back to a raw
  message + `malformed` flag (`sylo/parser.py`).
- **`sylo/webapp`** — FastAPI + htmx, reads only from the SQLite index and
  the control-plane DB, never the raw text files, never talks to the
  receiver process directly (reads its health via the status-file above).
- **`sylo/retention`** — daily background job, drops whole expired monthly
  partitions (index DB + matching raw files), never touches the current one.

Each has its own `config.py` (env-var only, no config files — see the
`SYLO_*` table in the README) and its own `main.py` entry point. On Windows
each also has a `winservice.py` (pywin32 `ServiceFramework` wrapper); on
Linux they run as plain processes under systemd units in `deploy/systemd/`.

## Data layout

- Raw: `data/raw/<source_ip>/<YYYY-MM-DD>.log`, append-only, one file per
  device per day.
- Index: `data/index/<YYYY-MM>.sqlite3`, one DB per month (WAL mode), with
  an FTS5 table (`messages_fts`) for free-text search. Rebuildable from raw
  files via `python -m sylo.indexer.rebuild` if the DB is lost/corrupted.
- Control plane: `data/app.sqlite3` (`sylo/webapp/appdb.py`) — `users`,
  `sessions`, `settings` tables. Different lifecycle than the index (never
  rotated/dropped), so deliberately a separate file.
- All timestamps are stored/queried in **UTC only**
  (`sylo/timeutil.py::format_receipt_time`). The browser converts to local
  time client-side (`sylo/webapp/static/localtime.js`, runs on page load
  and on every htmx swap) — never add server-side timezone logic.

## Webapp internals (`sylo/webapp/`)

- `auth.py` — bcrypt passwords, server-side sessions (random token in an
  HTTP-only cookie), per-session CSRF token, `LoginRateLimiter` (in-memory,
  per-IP). `Session` has `role` (`"admin"` / `"viewer"`) and an `is_admin`
  property, read fresh from the `users` table on every request — no
  caching, so deactivating a user revokes access mid-session.
- `deps.py` — `get_session` (401/redirect if not logged in) and
  `require_admin` (403 if logged in but not admin). Every route depends on
  one of these two.
- `routes/` — one module per page/feature (`messages.py`, `devices.py`,
  `settings.py` retention, `users.py` user management, `auth.py` login/
  logout/self-service password change, `health.py` bare `/healthz`).
- `queries.py` — all message/device read queries; fans out across the
  recent monthly index DBs and merges results (pagination is exact per
  page, not globally).
- Frontend is server-rendered Jinja2 + htmx, **no build step** — any new
  client-side behavior is a vendored plain `<script>` in `static/`,
  following the existing IIFE-with-event-listeners style (`localtime.js`,
  `userpanel.js`), loaded via `base.html`'s `{% block scripts %}`.
- No DB migration system exists — schema changes go directly into
  `appdb.SCHEMA`'s `CREATE TABLE IF NOT EXISTS`. Pre-v1, so existing
  installs are expected to be purged/reinstalled rather than migrated in
  place; revisit this once that's no longer true.
- The app always serves itself under a fixed mount point, `WebConfig.url_prefix`
  (`/sylo`, not env-configurable — see the comment above that field). Every
  route lives there (`app.py` wraps all routers in one `APIRouter(prefix=...)`),
  and every template/redirect/cookie path is baked with it too — this is for
  reverse-proxying behind nginx with `proxy_pass` pointed at the backend with
  no URI (so nginx forwards the request line untouched; sylo's own routes
  must already match it). Bare `/` and bare `/healthz` are also still
  registered unprefixed, for local/direct access and monitoring. Any new
  hardcoded absolute path in a route or template is almost certainly a bug —
  it needs `{{ url_prefix }}` (templates) or `config.url_prefix` (Python).

## Packaging

- **Windows**: PyInstaller onefile builds (`packaging/pyinstaller/*.spec`,
  one exe per process) + an Inno Setup installer (`packaging/inno/sylo.iss`)
  that registers all three as Windows services with independent
  start/stop/restart, writing each service's `SYLO_*` config into its own
  registry `Environment` value. The `.iss` script's `[Code]` section is
  large and has absorbed several hard-won fixes (service-file-unlock
  polling, upgrade-vs-fresh-install wizard-page skipping) — read the
  comments there before changing install/upgrade flow.
- **Linux**: `make install` builds a venv under `/opt/sylo` and installs
  systemd units from `deploy/systemd/`; `AmbientCapabilities=CAP_NET_BIND_SERVICE`
  lets the receiver bind port 514 as a non-root `sylo` user.

## Testing

`pytest` (venv at `.venv/`, run via `.venv/Scripts/python.exe -m pytest` on
Windows). Each `tests/test_*.py` file is self-contained — no shared
conftest/fixtures across files; e.g. `make_client`/`login`/`csrf_token`
helpers for `TestClient`-based webapp tests are small enough that each test
file defines its own copy rather than importing across files.

## Project history

`doc/sylo-plan.md` (removed) was the original design-and-build log — long
and increasingly redundant with the code itself. `doc/open_issues.md`
tracks small, deliberately-parked gaps going forward instead.
