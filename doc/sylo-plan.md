# Self-Contained Syslog Recorder — Project Plan

## Scale targets (derived)
- Devices: 100 nominal, design for 1,000 (10x headroom)
- Volume: ~300/device/day nominal → up to ~300,000 msgs/day at 10x
- Retention: 1 year default, configurable → up to ~110M rows/year at ceiling
- Implication: SQLite is fine for this volume with proper indexing, but plan for monthly file/table partitioning so no single file grows unbounded and old partitions can be dropped in O(1) instead of deleted row-by-row.

## Deployment
- v1 ships localhost-only (bind 127.0.0.1)
- Design decisions (auth, config, HTTP layer) must not preclude later LAN binding + reverse proxy in front for cloud/scale deployment.

---

## 1. Receiver (syslog listener) spec
- [x] Protocol support: UDP 514 (primary), TCP 514 (reliable option, newline-delimited framing), both RFC3164 and RFC5424 parsing supported, malformed input tolerated (never raises, falls back to raw message + `malformed` flag)
- [x] Concurrency model: **single asyncio event loop** for UDP/TCP ingest + small shared bounded thread pool (4-8 threads via `run_in_executor`) for actual file write/fsync calls. Event loop callback only parses device ID and enqueues — never touches disk directly.
  - Per-device isolation: one file + one `asyncio.Queue` + one writer coroutine per device, **keyed by source IP address** (not the parsed hostname field — a malformed/spoofed packet must not be able to inject an arbitrary device identity or path-unsafe characters into the file/queue key); a slow/stalled write for device X cannot block device Y (only shares the small executor pool, not the event loop).
  - Flush policy: writer flushes on buffer size/count threshold OR idle timer (~1s) elapse, whichever first — balances write batching against read freshness. fsync on a separate, slightly longer interval (~2s).
  - Overload detection: bounded per-device queue; soft threshold logs a warning + increments a lag counter, hard cap drops messages for that device only (never blocks ingest) + increments a drop counter. Counters exposed via health/metrics endpoint.
- [x] Message envelope: capture receipt timestamp, source IP, raw bytes, parsed fields (facility, severity, host, tag, msg)
- [x] Write path: append-only to **daily** rotating text files, one file per device per day (independent of the monthly SQLite partitioning in section 2 — a folder-per-day layout stays simple even if retention grows well past a year). fsync policy: see flush policy above (~2s interval).
- [x] Backpressure/overload behavior defined (what happens if disk or indexer stalls — must not block socket accept)
- [ ] Runs as independent Windows service, no dependency on UI process
- [ ] Crash/restart behavior: safe resume, no data loss/corruption of in-progress file

## 2. Storage / indexer spec
- [ ] Source-of-truth: rotating plain text files (open format, always readable even if index breaks)
- [ ] Index: SQLite (WAL mode), schema with indexes on (timestamp, host, severity, facility)
- [ ] Partitioning strategy: one DB/table-set per month to bound size and simplify retention drops
- [x] Indexer placement: **embedded in receiver process** (own asyncio task/queue, not the UI process). Chosen over separate process — write path is expected to stabilize quickly and change rarely, while search/lookup will see considerable rework, so isolating "likely to change" (indexer/UI) from "rarely changes" (receiver) matters more here than a hard process boundary.
  - Safety nets to preserve ingest isolation despite sharing a process:
    - Each message's parse+insert wrapped in its own try/except — malformed input must never raise into the ingest loop
    - Indexer has its own queue + task, same pattern as per-device writers — slow SQLite operations delay indexing only, never ingest
    - Batched commits (N rows or T seconds) to bound lock/fsync overhead per operation
    - Lag/backlog counter for the indexer (mirrors the write-side overload counter) exposed via health endpoint
- [ ] Recovery: indexer can rebuild index from text files if SQLite is lost/corrupted

## 3. HTTP / UI spec
- [ ] Server: FastAPI + uvicorn (Python), single process, separate from receiver
- [ ] Bind: 127.0.0.1 only in v1; config flag reserved for future LAN bind
- [ ] API: paginated `/api/messages` with filters (host, severity, facility, time range, free-text)
- [ ] Live tail: WebSocket or SSE endpoint
- [ ] Frontend: server-rendered + htmx (no SPA build step)
- [ ] Read path only touches SQLite index, never raw files, never blocks receiver
- [ ] `/healthz` endpoint for supervisor/auto-restart
- [ ] Pages: message browser/search, live tail, retention settings, device/source list

## 4. Retention manager spec
- [ ] Default: 1 year, user-configurable (per-install setting, UI-editable)
- [ ] Deletion granularity: drop whole monthly DB partitions; for raw text files (daily, per device — see receiver spec) delete all daily files whose date falls inside the dropped month, rather than row-by-row
- [ ] Schedule: periodic background job (daily), independent of receiver and UI
- [ ] Safe-guard: never deletes current/active partition

## 5. Packaging / installer spec
- [x] Installer tooling: **Inno Setup** — simplest scripting for bundling multiple exes + installing Windows services + custom install/data paths + uninstall-preserves-data logic; single self-contained setup.exe. (WiX/MSI worth revisiting only if later pushed via enterprise GPO/SCCM.)
- [ ] Bundles: receiver service, indexer, UI service (PyInstaller or similar for Python parts), default config
- [ ] Installs both processes as Windows services with independent start/stop/restart
- [ ] Default install/data paths, upgrade/uninstall behavior (data retained on uninstall unless user opts out)
- [ ] No external runtime dependencies required (no separate Python/DB install needed by end user)

## 6. Auth / security spec
- [x] Auth model: single local admin account (created at install/first-run), backed by a real `users` table (id, username, password_hash, created_at) rather than a hardcoded credential — keeps the door open to adding accounts later without redesign. Password hashed with **bcrypt** (chosen over argon2: simpler pure-Python packaging for PyInstaller, no C-extension build headaches; security difference is not material at single-local-admin scale). Server-side sessions (random token in HTTP-only cookie, session data kept server-side). Login rate-limiting/backoff on repeated failures. CSRF protection on state-changing endpoints (retention settings, config). One policy applied consistently regardless of whether accessed via localhost or later via reverse proxy.
- [ ] TLS: not needed for localhost v1; reverse proxy handles TLS termination at scale-out stage
- [ ] Input validation on receiver side against malformed/oversized/malicious syslog payloads (parser must never crash on garbage input)

## 7. Testing / validation plan
- [ ] Load test: sustained 300k msgs/day equivalent burst/sustained rate, confirm no message loss
- [ ] Crash-isolation test: kill UI process under load, confirm receiver keeps recording w/ zero loss
- [ ] Crash-isolation test: kill/corrupt SQLite index, confirm receiver unaffected and index rebuildable
- [ ] Retention test: confirm partitions age out correctly, disk usage bounded over time
- [ ] Malformed input fuzzing against receiver parser
- [ ] Installer test: clean Windows VM, install/uninstall/upgrade cycle
- [ ] Long-run soak test (days) for memory leaks / file handle leaks in receiver and UI

---

## Open decisions still needed before implementation starts
1. ~~Async vs threaded model for receiver~~ — **resolved**: asyncio + shared bounded executor pool, per-device queues/writers (see Receiver spec above)
2. ~~Indexer as its own process or embedded in receiver~~ — **resolved**: embedded in receiver, with per-message exception isolation, own queue, batched commits, lag counter (see Storage/indexer spec above)
3. ~~Installer tooling~~ — **resolved**: Inno Setup
4. ~~Single password vs accounts for v1 auth~~ — **resolved**: single local admin account, bcrypt-hashed, real `users` table for future extensibility (see Auth/security spec above)
