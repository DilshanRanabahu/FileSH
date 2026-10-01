# AGENTS.md

Instructions for AI coding agents working on **FileSh**.

## Project overview

FileSh is a local network file and folder sharing app. A Python server runs on the Windows PC; phones, tablets, and other computers on the same Wi‑Fi or wired network connect through a web browser by scanning a QR code (or entering a PIN). No app is installed on the phone, and no traffic leaves the local network.

- Feature list and build order: [docs/features.md](docs/features.md)
- UI rules, colours, layouts: [docs/design.md](docs/design.md)
- Security risks, rules, and checklists: [docs/SECURITY.md](docs/SECURITY.md)

Read all three files before starting any task.

## Tech stack

| Part | Choice |
|---|---|
| Language | Python 3.12 |
| Server | FastAPI + Uvicorn (`websockets` for live updates) |
| Uploads | Resumable: `POST /api/uploads` starts, `PUT /api/uploads/{id}?offset=N` streams raw bytes to disk with `aiofiles` |
| Folder watcher | `watchfiles` (tells browsers about changes made in Explorer) |
| Images | `Pillow` (thumbnails, tray icon); `qrcode` (SVG QR codes) |
| Discovery | `zeroconf` (mDNS name `filesh.local`) |
| HTTPS | `cryptography` (self-signed certificate) |
| Tray | `pystray` |
| Frontend | Plain HTML, CSS, JavaScript ES modules (no framework, no build step) |
| Tests | `pytest` + Starlette `TestClient` (`httpx2`); a real Uvicorn server for memory tests |
| Lint/format | `ruff` |
| Packaging | PyInstaller (`scripts\build.ps1` → `dist\FileSh.exe`) |

Do not add new dependencies without a clear reason. Never add a frontend framework, bundler, or CSS library. Never load anything from a CDN: the app must work with no internet connection.

## Project structure

```
FileSh/
├── app/
│   ├── main.py          # create_app(): middleware, routers, error handlers, lifespan
│   ├── runner.py        # main(): startup, servers (HTTP / HTTPS), restart, single instance
│   ├── config.py        # Settings (env vars + saved settings.json), paths, limits
│   ├── context.py       # AppContext: shared state, sharing on/off, background jobs
│   ├── security.py      # token, PIN, devices, require_access/require_local, middleware
│   ├── events.py        # WebSocket hub and shared-folder watcher
│   ├── transfers.py     # Accept/Reject requests and resumable uploads
│   ├── history.py       # transfer history (JSON) and shared texts (memory)
│   ├── media.py         # folder ZIP streaming, preview types, thumbnails
│   ├── desktop.py       # folder picker, Explorer, start with Windows, folder checks
│   ├── discovery.py     # mDNS (filesh.local)
│   ├── tls.py           # HTTPS certificate
│   ├── tray.py          # tray icon and menu
│   ├── utils.py         # safe_path(), clean_filename(), clean_folders(), IP, QR code
│   ├── routes/
│   │   ├── core.py      # page, status, connect/QR, PIN, stop/start, devices, /ws
│   │   ├── files.py     # list, download, ZIP, preview, thumbnail, uploads
│   │   ├── share.py     # transfers (accept/reject), texts, history
│   │   └── settings.py  # settings, folder picker, open folder, restart
│   └── static/          # the web page, served at /static/
│       ├── index.html
│       ├── style.css
│       ├── icons.svg        # SVG sprite of Lucide icons, used as <use href="...#name">
│       ├── favicon.svg
│       └── js/
│           ├── main.js      # start-up, status, screens, tabs, dark mode
│           ├── api.js       # fetch helpers and ApiError
│           ├── dom.js       # element, icon, toast, format, and clipboard helpers
│           ├── state.js     # shared state and hooks (avoids import cycles)
│           ├── live.js      # WebSocket with reconnect
│           ├── files.js     # file list, thumbnails, ZIP, preview
│           ├── uploads.js   # choosing, drag and drop, approval wait, resumable uploads
│           ├── texts.js     # Text tab
│           ├── history.js   # History tab
│           ├── settings.js  # Settings tab and restart
│           ├── connect.js   # PC: QR, PIN, devices, stop/start, incoming requests
│           └── pin.js       # PIN screen
├── shared/              # default shared folder when run from source (git-ignored)
├── tests/
│   ├── conftest.py      # fixtures: pc, phone (token cookie), stranger (no token), upload()
│   ├── test_files.py    # listing, upload/resume, download, ZIP, preview, large files
│   └── test_security.py # attack tests from SECURITY.md, approvals, settings, WebSocket
├── docs/
│   ├── features.md      # feature list and build order
│   ├── design.md        # UI rules, colours, layouts
│   ├── SECURITY.md      # risks, protections, tests, checklists
│   └── images/
│       └── banner.svg   # README banner
├── scripts/
│   └── build.ps1        # builds dist\FileSh.exe (temporary files in build\)
├── FileSh.pyw           # double-click launcher without a console
├── requirements.txt     # app dependencies (pinned)
├── requirements-dev.txt # test, lint, and build tools (pinned)
├── pyproject.toml       # project version, ruff and pytest settings
├── README.md            # how to use FileSh (for people, not agents)
├── AGENTS.md
└── CLAUDE.md
```

Keep this structure: code in `app/`, documents in `docs/`, helper scripts in `scripts/`, and nothing new at the top level unless a tool requires it there. If a module grows too large, split it inside `app/` (or `app/static/js/`) and update this section.

Generated folders are git-ignored: `.cache/` (ruff and pytest), `build/`, `dist/`, and `__pycache__/` are safe to delete; `.venv/` can be recreated with the set-up commands below.

FileSh's own data (settings, history, thumbnails, certificate, log) lives in `%LOCALAPPDATA%\FileSh`, never in the shared folder.

## Commands

The environment is **Windows**, with PowerShell as the shell.

```powershell
# Set up
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements-dev.txt

# Run (tray icon + browser; listens on all network interfaces so phones can connect)
python -m app.main
python -m app.main --no-tray      # console only, Ctrl+C to stop
python -m app.main --minimized    # don't open the browser

# Optional environment variables
$env:FILESH_PORT = "8010"            # default 8000 (HTTPS mode also uses port + 1)
$env:FILESH_SHARED_DIR = "D:\Share"  # default shared folder (a folder saved in Settings wins)
$env:FILESH_DATA_DIR = "D:\FileShData"
$env:FILESH_HOST = "127.0.0.1"       # this PC only: no phones, no firewall prompt (testing)

# Test
pytest

# Lint and format
ruff check .
ruff format .

# Check libraries for known security problems
pip-audit -r requirements.txt -r requirements-dev.txt

# Build dist\FileSh.exe
powershell -ExecutionPolicy Bypass -File scripts\build.ps1
```

Before finishing a task, run `ruff check .` and `pytest`, and make sure both pass. Check JavaScript syntax with `node --check app/static/js/<file>.js`. Before finishing a version, also run `pip-audit` and `/security-review` (see [SECURITY.md](docs/SECURITY.md#4-how-to-check-before-each-release)).

## Workflow

1. Build features **one version at a time**, in the order in [features.md](docs/features.md). Do not start a later version's features unless asked.
2. When a feature is finished and passes the automated tests, tick its checkbox in `features.md` (`- [x]`), and the matching security items in `SECURITY.md` section 3. A **version** is only marked done after the real-phone test.
3. Keep changes small and focused on the task. Do not refactor unrelated code.
4. If a decision is not covered by `features.md`, `design.md`, or this file, ask the user rather than guessing.

## Coding rules

### Python

- Follow PEP 8; format with `ruff format`.
- Use type hints on all functions.
- Use `async def` for route handlers and `aiofiles` for streaming file I/O. Run other blocking work (directory listing, thumbnails, PowerShell, registry, zeroconf) with `asyncio.to_thread`.
- Use `pathlib.Path`, not string paths.
- Keep settings and limits in `app/config.py`; no hard-coded values elsewhere. Settings changed on the Settings page are saved with `Settings.save()`.
- Routes get shared state with `get_ctx(request)`; never use module-level globals for state.
- Change sharing on/off only through `AppContext.set_sharing()`, so devices are disconnected and the PC page is told.
- After changing files, texts, or history, send the matching live event through `ctx.hub` (`files_changed()`, `{"type": "texts"}`, `{"type": "history"}`).
- Return clear JSON errors: `{"error": "File not found"}` with the correct status code.

### JavaScript

- Plain ES modules, `const`/`let`, `async`/`await`. One module per area (see the structure above); cross-module calls that would create import cycles go through `hooks` in `state.js`.
- Use `XMLHttpRequest` for uploads (it reports upload progress); `fetch` (via `api.js`) for everything else.
- No inline `onclick` handlers, inline `<script>`, or `style=""` attributes: the Content Security Policy blocks them. Use `addEventListener` and CSS classes (setting `element.style.width` from JavaScript is fine).
- Set text with `textContent`, never `innerHTML`, `outerHTML`, `insertAdjacentHTML`, `document.write`, or `eval`.
- `localStorage` only for small per-device conveniences (theme, last tab), always through `storage` in `dom.js`.

### CSS

- Use only the CSS variables and spacing scale defined in [design.md](docs/design.md). Every colour needs a light and a dark value.
- Phone-first: base styles for small screens, `@media (min-width: 768px)` for PC.
- Do not add colours, fonts, shadows, or animations that are not in `design.md`.

## File handling rules

These rules are required. Breaking them causes crashes or data loss.

- **Stream everything.** Read and write files in chunks (1 MB). Never load a whole file into memory. Files can be 10 GB or more.
- **Never overwrite.** If a file exists, save as `name (1).ext`, `name (2).ext`, and so on (`unique_path()` under `ctx.rename_lock`).
- **Write safely.** Upload to a temporary `.filesh-<id>.part` file, then rename it when complete. Keep the part file when the connection drops (so the upload can resume); delete it when the upload is cancelled, after 24 hours, or at start-up.
- **Zip on the fly.** Stream folder ZIPs directly to the response (`zip_folder()`); never create the ZIP on disk first.
- **Handle names from any device.** Support Unicode file names (Sinhala, Tamil, emoji, iPhone NFD) and strip characters Windows does not allow: `< > : " / \ | ? *`.

## Security rules

FileSh exposes the PC's files to the network. **[SECURITY.md](docs/SECURITY.md) is the full source of truth**; follow every rule in it. The most important ones:

- **Path safety:** every path from a request goes through the single `safe_path()` helper in `app/utils.py`, which keeps it inside the shared folder. Folder uploads go through `clean_folders()`.
- **Access:** every API route uses `require_access` or `require_local` from `app/security.py`; the WebSocket uses `has_access()`. The token is `secrets.token_urlsafe(32)`, new at every start, compared with `secrets.compare_digest()`.
- **QR code, token, PIN, settings, history, and accept/reject are PC only** (`request.client.host` is `127.0.0.1` or `::1`). Never trust `X-Forwarded-For`.
- **Approvals:** with "Ask before receiving files" on, uploads from other devices must match an accepted request for the same device.
- **Host and Origin checks** on every request and WebSocket; no CORS headers.
- **Clean every uploaded file and folder name** (Windows reserved names, illegal characters, `..`).
- **Security headers** (CSP, `nosniff`, `X-Frame-Options`, `Referrer-Policy`, `Cache-Control`) on every response, from one middleware.
- **Downloads** always use `Content-Disposition: attachment`; only types in `PREVIEW_TYPES` are shown inline.
- **Limits:** free disk space, max file size, parallel uploads, 2 MB for non-file request bodies (checked before reading).
- **Local network only:** no port forwarding, UPnP, tunnels, or internet access.
- **Never log** the token, PIN, cookies, or file contents. Errors never show full PC paths or stack traces.

If a new feature adds a new risk that `SECURITY.md` does not cover, add it to `SECURITY.md` (risk, protection, test) before writing the code.

## Testing

- Add tests in `tests/` for every route and every helper in `app/utils.py`.
- Add the attack tests listed under each "Test:" in [SECURITY.md](docs/SECURITY.md) section 2 as automated tests.
- Use the fixtures in `conftest.py`: `pc` (the PC itself), `phone` (has the token), `stranger` (no token), and `upload()` for the two-step upload. Approval tests use the `asking` fixture.
- The autouse fixture `no_desktop_side_effects` stops tests from running PowerShell, changing the registry, or opening windows. Keep it that way.
- WebSocket tests must use the full URL `ws://localhost:8000/ws`; the test client otherwise sends `Host: testserver`, which the Host check rejects.
- Test uploads and downloads with a large generated file against a real Uvicorn server to confirm memory stays low (`TestClient` keeps bodies in memory).
- Use temporary folders (`tmp_path`) for the shared and data folders in tests; never touch the real `shared/` folder or `%LOCALAPPDATA%\FileSh`.

## Windows notes

- The network profile must be **Private**, or Windows Firewall blocks other devices. FileSh prints the firewall commands at start-up and warns on Public networks.
- The server listens on `0.0.0.0` (or `FILESH_HOST`); phones can't connect to `127.0.0.1`.
- With HTTPS on, phones use `https://<ip>:8001`, and the PC's own page stays on `http://localhost:8000` (bound to `127.0.0.1` only).
- Detect the PC's LAN IP address (for example `192.168.x.x`) for the QR code; skip `127.*` and `169.254.*`.
- The router's AP/client isolation must be off, and devices must not be on a guest network.
- Without a console (`FileSh.pyw` or the `.exe`), output goes to `%LOCALAPPDATA%\FileSh\filesh.log`.

## Do not

- Commit `shared/`, `.venv/`, `build/`, `dist/`, `__pycache__/`, or `*.part` files.
- Add user accounts, a database, cloud features, or internet access (see "Out of scope" in `features.md`).
- Change the design (colours, fonts, layout) without updating `design.md`.
- Mark a feature as done in `features.md` without testing it.
- Weaken or skip a rule from `SECURITY.md` to make a feature easier, even temporarily.
- Add a dependency without pinning its exact version in `requirements.txt` or `requirements-dev.txt`.
