# Sylo

Sylo is a self-contained syslog recorder: it listens for syslog messages
(UDP/TCP 514, RFC3164 and RFC5424). It records them to per-device
text files and indexes them into SQLite for fast search. A local web UI
lets you browse/search history, tail messages live, manage retention, and
see which devices are reporting in.

It is intended for monitoring edge devices in small-scale deployments
where a full-fledged and IT-heavy syslog solution would introduce more problems
than it solves.

Some more information and Windows installer binary can be found [here](https://philea.my-system.nl/pages/sylo).

It's made up of three independent processes, each of which can be started,
stopped, and restarted without affecting the others:

- **Receiver** (`sylo.receiver`) — listens on UDP/TCP 514, writes raw
  messages to daily per-device text files, and keeps a searchable index.
- **Webapp** (`sylo.webapp`) — FastAPI + htmx UI on `127.0.0.1:8514` by
  default (configurable via `SYLO_WEB_PORT`): message browser/search, live
  tail (SSE), retention settings, device list.
- **Retention manager** (`sylo.retention`) — a daily background job that
  drops whole monthly partitions once
  they're older than the configured retention window.

## Building

### Windows

This produces three self-contained `.exe` files (no separate Python install
needed on the target machine) and, eventually, a single installer built
with Inno Setup.

From the repository root, in PowerShell:

```powershell
py -3.11 -m venv .venv
.venv\Scripts\Activate.ps1

python -m pip install --upgrade pip
pip install -e ".[build]"

pyinstaller packaging\pyinstaller\receiver.spec  --distpath dist --workpath build
pyinstaller packaging\pyinstaller\webapp.spec    --distpath dist --workpath build
pyinstaller packaging\pyinstaller\retention.spec --distpath dist --workpath build
```

Verify each exe at least starts up and responds to pywin32's own CLI:

```powershell
.\dist\sylo-receiver.exe --help
.\dist\sylo-webapp.exe --help
.\dist\sylo-retention.exe --help
```

(If PowerShell blocks the venv activation script with an execution-policy
error, run `Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass`
first, or activate via `.venv\Scripts\activate.bat` in `cmd.exe` instead.)

The next step -- compiling `packaging\inno\sylo.iss` with Inno Setup's
`ISCC.exe` into a single `sylo-setup.exe` installer:

```powershell
"C:\Program Files (x86)\Inno Setup 6\ISCC.exe" packaging\inno\sylo.iss
```

Build/run-verified on a real Windows machine: compiles clean and a full
install registers, configures, and starts all three services, and an
upgrade (re-running the installer over an existing install) completes
cleanly too.

### Linux

**Development**, or just trying it out without installing anything system-wide:

```bash
python3 -m venv .venv
source .venv/bin/activate

pip install --upgrade pip
pip install -e ".[dev]"   # add pytest etc.; drop the extra for a runtime-only install

pytest -q                 # optional: confirm the test suite passes
```

**A real install**, running as systemd services: `sudo make install`. This is not a `.deb`/`.rpm`/Docker image --
it builds a venv under `/opt/sylo` from this source tree (via `pip install
.`, no `-e`, so the clone directory is disposable afterward), creates a
system `sylo` user, and installs `sylo-receiver.service`,
`sylo-webapp.service`, and `sylo-retention.service` under
`/etc/systemd/system/`. Data lives under `/var/lib/sylo/data`, config in
`/etc/sylo/sylo.env` (copied from `deploy/systemd/sylo.env.example` on first
install only -- re-running `make install` to upgrade never overwrites it).
See `Makefile` for exactly what it does before running it with root.

```bash
sudo make install
$EDITOR /etc/sylo/sylo.env          # set SYLO_ADMIN_PASSWORD before first start
sudo systemctl enable --now sylo-receiver sylo-webapp sylo-retention
```

`sudo make uninstall` stops the services and removes `/opt/sylo`, but keeps
`/var/lib/sylo/data` and `/etc/sylo` (mirrors the Windows installer's
keep-data-by-default uninstall). `sudo make purge` removes those too, along
with the `sylo` user, for a fully clean removal.

## Setup

Ob both platforms all three processes are configured entirely
through environment variables (no config file). The ones that matter for a
first run:

| Variable              | Used by                       | Default              | Purpose                                    |
|------------------------|-------------------------------|-----------------------|---------------------------------------------|
| `SYLO_DATA_DIR`        | receiver, retention            | `./data/raw`          | Root of per-device raw text files          |
| `SYLO_INDEX_DIR`       | receiver, webapp, retention    | `./data/index`        | Monthly SQLite index files                 |
| `SYLO_APP_DB`          | webapp, retention               | `./data/app.sqlite3`  | Control-plane DB (users/sessions/settings) |
| `SYLO_ADMIN_PASSWORD`  | webapp                         | *(random, first run)* | Password for the default `admin` account   |

**Set `SYLO_DATA_DIR`, `SYLO_INDEX_DIR`, and `SYLO_APP_DB` to the same
values for all three processes** so they agree on where the data lives —
otherwise, e.g., the webapp won't see what the receiver wrote. The relative
defaults (`./data/...`) only make sense if all three are started from the
same working directory; for anything long-running, point them at an
absolute path instead.

Each process has a number of other tunable knobs (queue sizes, flush
intervals, page sizes, rate limits, etc.) — see `sylo/receiver/config.py`,
`sylo/indexer/config.py`, `sylo/webapp/config.py`, and
`sylo/retention/config.py` for the full list; the defaults are reasonable
for the scale this was designed for and shouldn't need changing.

### Admin account

On its first run, the webapp creates a single `admin` account. Set
`SYLO_ADMIN_PASSWORD` before that first run to choose the password
yourself; if you leave it unset, one is generated and logged once via
Python's `logging` module. **On Windows, prefer setting it explicitly** —
a Windows service has no attached console, so a generated password's log
line currently has nowhere visible to go (a known, documented gap; see the
note at the top of `packaging/inno/sylo.iss`). The Inno Setup installer
also has its own wizard page for this, feeding it into the webapp service's
environment directly.

### Running it

**Windows, via the installer** (once `sylo-setup.exe` exists — see above):
running it installs all three services (`SyloReceiver`, `SyloWebapp`,
`SyloRetention`), wires up the environment variables above for you, starts
them, and leaves them registered for auto-start on boot. Nothing further
to do — the installer prompts for the webapp's port (default `8514`) and
puts a "Sylo" shortcut in the Start Menu (and optionally the desktop) that
opens it directly in your browser; log in as `admin`.

**Windows, running the exes directly** (without the installer, e.g. to
test a build): each exe is dual-mode, per pywin32's `HandleCommandLine` —
`--startup=auto install`, `start`, `stop`, `remove` manage it as a service
(the `--startup` option must precede the command, not follow it -- pywin32
parses argv with plain `getopt`, which stops recognizing options after the
first positional argument),
but with no arguments it expects to be launched *by* the Service Control
Manager, not run directly from a console. To just run something in the
foreground for testing, use the plain Python entry points instead (from an
activated venv, with the env vars above set):

```powershell
python -m sylo.receiver.main
python -m sylo.webapp.main
python -m sylo.retention.main
```

**Linux, real install**: `sudo systemctl enable --now sylo-receiver sylo-webapp
sylo-retention` after `sudo make install` (see above) — the unit files
already grant the receiver `CAP_NET_BIND_SERVICE` so it can bind port 514
without running as root, and handle start/stop/restart/auto-start-on-boot.

**Linux, ad hoc from a dev venv** (no systemd, e.g. just trying it out): same
plain Python entry points, one per terminal (or backgrounded with
`nohup ... &`, or under your own supervisor of choice):

```bash
export SYLO_DATA_DIR=/path/to/data/raw
export SYLO_INDEX_DIR=/path/to/data/index
export SYLO_APP_DB=/path/to/data/app.sqlite3
export SYLO_ADMIN_PASSWORD=choose-a-password   # first run only
export SYLO_WEB_PORT=8514                      # optional, this is the default

python -m sylo.receiver.main &
python -m sylo.webapp.main &
python -m sylo.retention.main &
```

One Linux-specific catch: UDP/TCP port 514 is privileged. Either run the
receiver as root, or grant the capability to the venv's Python once instead
of running everything as root:

```bash
sudo setcap 'cap_net_bind_service=+ep' "$(readlink -f .venv/bin/python3)"
```

(This grants the capability to the interpreter binary itself, so anything
run by that same venv's Python gets it too — fine for a throwaway dev venv,
which is why the real install above uses per-unit `AmbientCapabilities`
instead, scoped to just the receiver service.)

Then, on any platform, visit `http://127.0.0.1:8514` (or the port you
set `SYLO_WEB_PORT` to) and log in as `admin`
with whichever password you set (or the one that was logged, if you didn't
set one).


## Troubleshooting
In case port 514 is already taken or blocked, the syslog recorder can't
get hold of it. You will see an error message when opening the web interface. On Windows this
could be caused by a third party firewall or virus checker that blocks the port, or the
presence of Docker or WSL. Standard firewall functionality just drops the traffic, this will go unnoticed so there is no error message and no data.
The Windows Installer writes a firewall rule to avoid that.
How to solve such problems is out of scope for Sylo. Some effort has been taken to try prevent it and/or make it visible.

## Authors
Built with Claude Code as a much valued implementation- and troubleshooting aid - architectural
decisions were mine.
