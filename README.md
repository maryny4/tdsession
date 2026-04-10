<div align="center">

# tdsession

**Multi-session Telegram Desktop viewer in Docker**

Launch and manage multiple Telegram accounts simultaneously through your browser.
Supports Telethon, Pyrogram, and Kurigram session formats with automatic detection.

[![Docker](https://img.shields.io/badge/Docker-ready-2496ED?logo=docker&logoColor=white)](#quick-start)
[![License](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![Platform](https://img.shields.io/badge/Platform-linux%2Famd64-lightgrey)](#requirements)

</div>

---

## What it does

Drop your `.session` files into a folder, run one command, and get a web UI where you can:

- **View multiple accounts** — each runs in its own isolated VNC display
- **Switch instantly** — tab-based interface, all sessions stay alive
- **Auto-detect formats** — Telethon, Pyrogram, Kurigram recognized automatically
- **Share files** — built-in shared folder accessible from VNC file dialogs
- **Copy-paste** — seamless clipboard between host and VNC (Chrome/Edge)

<br>

## Quick Start

```bash
git clone https://github.com/hex4f/tdsession.git
cd tdsession

# Configure
cp .env.example .env

# Run
docker compose up -d

# Open
open http://localhost:6160
```

> Place your `.session` files into the `sessions/` folder (subfolders supported). They appear in the UI instantly.

<br>

## Project Structure

```
tdsession/
├── docker-compose.yml      # Run configuration
├── .env                     # Optional: WEB_PORT, MAX_SESSIONS, VNC_RESOLUTION
├── sessions/                # Your .session files (subfolders supported)
├── shared/                  # File exchange with VNC sessions
└── src/                     # Application source
    ├── backend/             # FastAPI server
    ├── frontend/            # Web UI
    ├── Dockerfile
    └── entrypoint.sh
```

<br>

## Usage

| Action | How |
|--------|-----|
| **Add sessions** | Drop `.session` files into `sessions/` — they appear in the sidebar instantly |
| **Launch** | Select a session, click **Launch** |
| **Switch** | Click tabs to switch between running sessions |
| **Fullscreen** | Hover VNC area → click maximize icon (top right) |
| **Toggle sidebar** | Click panel icon in the top bar |
| **VNC toolbar** | Hover VNC area → sliders icon toggles KasmVNC control bar |
| **Share files** | Put files in `shared/` → accessible as "Shared" bookmark in VNC file dialogs |
| **Stop** | Click ✕ on a tab, or **Stop All** in the top bar |

<br>

## Clipboard

| Browser | Method |
|---------|--------|
| **Chrome / Edge** | Seamless — copy/paste works automatically between host and VNC. Click once inside VNC canvas after switching tabs. |
| **Safari / Firefox** | Use KasmVNC clipboard panel — toggle via sliders icon in VNC toolbar |

<br>

## Session Formats

| Format | Detection | First Launch |
|--------|-----------|-------------|
| **Pyrogram** | `test_mode` + `user_id` columns | Offline |
| **Kurigram** | `server_address` + `api_id` columns | Offline |
| **Telethon** | `server_address` only | Needs internet (fetches `user_id` once) |

Converted tdata is cached inside the container. Cache invalidates when the source `.session` file changes.

<br>

## Configuration

All settings are optional. Create `.env` in the project root:

```env
WEB_PORT=6160              # Web UI port (default: 6160)
MAX_SESSIONS=10            # Max concurrent sessions (default: 10)
VNC_RESOLUTION=1920x1080   # Initial VNC resolution (default: 1920x1080)
```

Each session uses approximately **170 MB RAM** (Xvnc + Fluxbox + Telegram Desktop).

To persist tdata cache across container rebuilds:

```yaml
# docker-compose.yml
volumes:
  - ./data:/app/data
```

<br>

## Architecture

Each session runs in complete isolation:

```
Browser → FastAPI :6160
            ├── /api/*             → Session Manager
            ├── /vnc/{id}/*        → HTTP proxy  → Xvnc :100+N
            └── /vnc/{id}/ws       → WS proxy   → Xvnc :100+N

Per session:
  Xvnc (display + VNC server)
  Fluxbox (window manager)
  Telegram Desktop (with converted tdata)
```

- Sessions are allocated X displays `:100` through `:100+N` with corresponding VNC ports
- KasmVNC web client provides browser-based remote desktop
- FastAPI reverse-proxies all VNC traffic per session
- Filesystem watcher pushes real-time updates via Server-Sent Events

<br>

## Requirements

- **Docker** + **Docker Compose**
- **x86_64** host recommended — ARM (Apple Silicon) works via QEMU emulation but is slower

<br>

## License

MIT
