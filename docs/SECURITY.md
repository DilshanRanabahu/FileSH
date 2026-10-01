# FileSh: Security

FileSh opens a door from the network into your PC's files. This document explains **who could misuse that door**, **how we block each risk**, and **how to test** that the protection works.

Every rule here is required. A feature is not finished until its security checks pass. The tests named below live in `tests/` (mostly `tests/test_security.py`) and run with `pytest`.

---

## 1. Who could attack?

| Who | Example |
|---|---|
| **Other people on the same Wi‑Fi** | A family member, guest, or stranger on a café or office network opens `http://192.168.1.10:8000` and browses your files. |
| **A bad website open in your browser** | While FileSh is running, a website you visit secretly sends requests to `localhost:8000` to read or upload files. |
| **A bad file** | Someone uploads a file with a dangerous name (`../../Windows/evil.exe`) or dangerous content (a web page with hidden scripts, a "bomb" image). |
| **Someone watching the network** | On a shared Wi‑Fi, a person with special tools reads files as they travel between phone and PC. |
| **A connected device that misbehaves** | A phone that was allowed in tries to send files the PC didn't accept, or floods the PC with requests. |

---

## 2. Risks and protections

Each risk has: **what could happen**, **how we protect**, and **how to test**.

### 2.1 Strangers on the network access your files

**What could happen:** anyone on the same Wi‑Fi opens the address and downloads or uploads files.

**Protection:**
- Generate a random **access token** at every start: `secrets.token_urlsafe(32)`. The QR code link contains it.
- Every API route and the WebSocket check the token. No token or wrong token → `401 Unauthorized`.
- Requests from the PC itself (`127.0.0.1` / `::1`) need no token: the PC can already see the token in the QR panel. Websites in the PC's browser are still blocked by the Host and Origin checks (2.4).
- After the first visit, the token moves from the URL into a **cookie** (`HttpOnly`, `SameSite=Strict`, `Secure` with HTTPS), and the page removes it from the address bar and history.
- Each device also gets a random **device ID cookie**, used to tie approvals and unfinished uploads to that device (2.15). Only `[A-Za-z0-9_-]{16,64}` is accepted.
- Compare tokens and PINs with `secrets.compare_digest()`, not `==`.
- **PIN:** a 6-digit PIN shown only on the PC, for devices that can't scan the QR code. **5 wrong attempts** block that IP address for 5 minutes. After **20 wrong attempts** from all devices together, a new PIN is made.
- Stopping and starting sharing makes a new token and PIN, so old QR codes stop working.

**Test:** `test_stranger_is_denied`, `test_wrong_token_gives_no_cookie`, `test_token_cookie_flags`, `test_wrong_pins_block_the_device`, `test_many_wrong_pins_from_many_devices_change_the_pin`. Manual: open the address on the phone without the QR code → PIN screen, not the files.

### 2.2 Reading files outside the shared folder (path traversal)

**What could happen:** an attacker requests `/api/download?path=../../Users/DilshanR/Documents/passwords.txt` and gets a file from anywhere on the PC.

**Protection:**
- One helper function `safe_path()` in `app/utils.py`. **Every** path from a request goes through it: listing, download, ZIP, preview, thumbnail, and upload.
- It joins the path to the shared folder, calls `.resolve()`, and checks the result is still inside the shared folder (`Path.is_relative_to()`). Otherwise → `403 Forbidden`.
- Reject absolute paths, drive letters (`C:`), `..` (also `...` and `.. `), and URL-encoded tricks (`%2e%2e`).
- Do not list, follow, or ZIP **symlinks or junctions**.

**Test:** `test_file_traversal_blocked`, `test_folder_traversal_blocked`, `test_junction_outside_is_blocked` (also checks the ZIP), `test_safe_path_rejects`.

### 2.3 Dangerous file and folder names on upload

**What could happen:** an uploaded file named `..\..\startup\virus.exe`, `CON.txt`, or `report.txt:hidden` is written to a wrong place, crashes Windows file handling, or hides data. A folder upload sends folder names like `../escape`.

**Protection:** `clean_filename()` cleans every uploaded name, and `clean_folders()` cleans **every folder name** of a folder upload the same way:
- Keep only the last part of the name, then pass the final path through `safe_path()`.
- Remove characters Windows does not allow: `< > : " / \ | ? *` and control characters.
- Remove trailing dots and spaces.
- Rename Windows **reserved names**: `CON`, `PRN`, `AUX`, `NUL`, `COM1`–`COM9`, `LPT1`–`LPT9` (also with an extension, like `con.txt`).
- Limit names to 200 characters and folder uploads to 32 levels deep.
- Empty name after cleaning → `file`.
- Never overwrite (save as `name (1).ext`).

**Test:** `test_clean_filename`, `test_clean_folders`, `test_folder_upload_names_are_cleaned`, `test_dangerous_upload_names_stay_in_shared_folder`.

### 2.4 A bad website attacks through your browser (CSRF and DNS rebinding)

**What could happen:** you visit a malicious website on the PC or phone while FileSh is running. That website sends hidden requests to FileSh using your browser, which already has the cookie or is on `localhost`.

**Protection:**
- **Host check:** accept requests only if the `Host` header is `localhost`, `127.0.0.1`, `[::1]`, one of the PC's own IP addresses, or `filesh.local` while discovery is on, with a FileSh port. Anything else → `400`. This blocks "DNS rebinding".
- **Origin check:** every request that changes something (`POST`, `PUT`, `DELETE`) must have an `Origin` equal to the FileSh address. Otherwise → `403`. WebSocket connections need a matching `Origin` too.
- Cookies use `SameSite=Strict`.
- No CORS: never add `Access-Control-Allow-Origin` headers.

**Test:** `test_bad_host_rejected`, `test_bad_origin_rejected`, `test_missing_origin_rejected`, `test_websocket_needs_same_origin`, `test_discovery_name_accepted_only_when_discoverable`.

### 2.5 Showing the QR code, token, and PIN to the wrong device

**What could happen:** a phone on the network opens the PC page and sees the QR code, token, and PIN, so it gets full access, or changes settings.

**Protection:**
- The QR / PIN panel and all PC-only routes (settings, history, devices, accept/reject, stop/start, restart, folder picker) are allowed **only** when `request.client.host` is `127.0.0.1` or `::1`.
- Never trust headers like `X-Forwarded-For` to decide this.
- The page's HTML is the same for everyone and never contains the token or PIN.

**Test:** `test_pc_only_routes`, `test_forwarded_header_does_not_make_device_local`, `test_page_source_has_no_token_or_pin`.

### 2.6 Hidden scripts in file names, text, or files (XSS)

**What could happen:** a file named `<img src=x onerror=alert(1)>.jpg` or a shared text runs a script when shown. Or an uploaded `.html` / `.svg` file runs scripts when opened in the browser and steals the token.

**Protection:**
- In JavaScript, show file names, text, and device names with `textContent`, **never** `innerHTML`, `outerHTML`, `insertAdjacentHTML`, `document.write`, or `eval`.
- Shared text becomes a link only when the whole text is one `http:` or `https:` URL; the link opens with `rel="noopener noreferrer"`.
- Downloads use `Content-Disposition: attachment` and `application/octet-stream`, so the browser saves the file instead of opening it.
- **Previews** are allowed only for a fixed list of image, video, and audio types (`PREVIEW_TYPES` in `app/media.py`). The content type comes from that list, never from the file content, and `nosniff` stops the browser from guessing. `html`, `svg`, `xml`, and `pdf` are never shown inline.
- Add the security headers in 2.8.

**Test:** `test_frontend_never_uses_html_injection`, `test_unsafe_types_are_never_previewed`, `test_preview_type_comes_from_extension_not_content`, `test_text_links_only_for_http`.

### 2.7 Filling up the disk or overloading the PC

**What could happen:** someone uploads huge files until the disk is full, sends a giant request, or sends thousands of requests, and the PC slows down or crashes.

**Protection:**
- Check free disk space before accepting an upload and before each upload part; keep at least **1 GB** free. Otherwise → `507`.
- Maximum file size (default **20 GB**) in `app/config.py`.
- At most **3 uploads at the same time** per device, and 1,000 unfinished uploads in total.
- Request bodies other than file data are limited to **2 MB**, checked in the middleware **before** the body is read. Shared text is limited to 100 KB.
- At most 3 transfer requests waiting for an answer per device, and 10,000 files per request.
- Only 2 thumbnails are made at the same time; images over 50 MB or 50 million pixels get no thumbnail (2.17).
- Delete unfinished uploads after 24 hours, and their `.part` files when FileSh starts.

**Test:** `test_file_too_large`, `test_not_enough_disk_space`, `test_too_many_parallel_uploads`, `test_body_larger_than_announced`, `test_json_body_size_limit`, `test_text_size_limit`, `test_too_many_waiting_requests`.

### 2.8 Missing browser security headers

**What could happen:** without these headers, browsers allow extra tricks such as loading FileSh inside another site (clickjacking) or leaking the token in links.

**Protection:** one middleware adds these headers to **every** response, including errors:

```
Content-Security-Policy: default-src 'self'; connect-src 'self' ws://<host> wss://<host>; img-src 'self' data: blob:; media-src 'self' blob:; object-src 'none'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'
X-Content-Type-Options: nosniff
X-Frame-Options: DENY
Referrer-Policy: no-referrer
Cache-Control: no-store
```

`<host>` is the already-checked `Host` header, so the live connection may only go back to the same PC. Because of the CSP, all JavaScript and CSS are separate files under `app/static/`. No inline `<script>`, `style=""`, or `on...=` attributes.

**Test:** `test_security_headers`, `test_security_headers_on_rejected_requests`, `test_websocket_only_allowed_to_same_host`, `test_html_has_no_inline_scripts_or_styles`.

### 2.9 Someone reading transfers on the network

**What could happen:** with plain HTTP, someone on a shared or public Wi‑Fi with network tools could read files as they travel.

**Protection:**
- If Windows reports the network as **Public**, the PC page and the console show a warning.
- The firewall rules FileSh suggests are for the **Private** profile only.
- **HTTPS** (Settings, off by default): a self-signed certificate (`app/tls.py`) for `localhost`, `filesh.local`, and the PC's IP addresses, valid 397 days and renewed automatically when the IP address changes or it nears expiry. Other devices connect on port 8001 over HTTPS; the PC's own page stays on HTTP at `localhost:8000`, which never leaves the PC.
- The Settings page shows the certificate's SHA-256 fingerprint, so it can be compared with what the phone's browser shows.

**Test:** `test_certificate_is_made_and_reused`. Manual: switch HTTPS on, restart, and open the QR code on the phone → the browser shows `https://` after the one-time warning.

### 2.10 Leaving the door open

**What could happen:** FileSh keeps running in the background for days, and the access stays open.

**Protection:**
- A new token and PIN on every start and every time sharing is started again.
- The PC page always shows how many devices are connected, and lists them.
- A **Stop sharing** button on the PC page and in the tray menu. Stopping disconnects every device immediately, including live connections.
- **Auto-stop** (default 30 minutes): sharing stops when no device has been connected for that long.

**Test:** `test_stop_and_start_sharing`, `test_websocket_closed_when_sharing_stops`, `test_auto_stop_after_no_activity`.

### 2.11 Leaking information in errors and logs

**What could happen:** error messages show full PC paths (`C:\Users\DilshanR\...`) or the token appears in log files.

**Protection:**
- API errors show short messages only: `{"error": "File not found"}`. Never full paths or Python stack traces.
- Never log the token, PIN, cookies, or file contents. The access log prints the path only, never the query string.
- Paths in the API are always **relative to the shared folder**.
- API documentation pages (`/docs`, `/openapi.json`) are switched off.

**Test:** `test_errors_do_not_show_paths`, `test_token_is_not_logged`, `test_api_docs_are_disabled`.

### 2.12 Vulnerable libraries

**What could happen:** a library FileSh uses has a known security bug.

**Protection:**
- Pin exact versions in `requirements.txt` and `requirements-dev.txt`.
- Run `pip-audit` before each version is finished and update libraries that have known problems.

### 2.13 Sharing the wrong folder

**What could happen:** on the Settings page, the shared folder is changed to `C:\`, `C:\Windows`, or the whole user folder, exposing system files, passwords, or browser data.

**Protection** (`validate_shared_folder()` in `app/desktop.py`):
- The folder must be a full path, exist, and allow saving files.
- Refuse whole drives, the user's home folder itself, Windows, Program Files, ProgramData, and AppData, plus any folder that **contains** one of these.
- Refuse FileSh's own data folder (settings, history, certificate key).
- Only the PC can change settings (2.5).
- Changing the folder cancels unfinished uploads and approvals for the old folder.

**Test:** `test_shared_folder_validation`, `test_change_shared_folder`.

### 2.14 Live updates and discovery

**What could happen:** a device without access listens to live events (file names, texts), or discovery broadcasts something secret to the whole network.

**Protection:**
- The WebSocket checks access (token cookie or the PC itself) and `Origin` before accepting, and checks access again on every message. When sharing stops, every device's connection is closed with code `4001`.
- Events only say *that* something changed (`{"type": "files", "paths": [...]}`); devices then load the data through the normal, checked API. Transfer requests are sent only to the PC.
- **Discovery (mDNS)** announces only the name `filesh.local`, the IP address, and the port; never the token or PIN. A device that finds FileSh this way still has to enter the PIN. Discovery can be switched off in Settings and is off when FileSh only listens on the PC (`FILESH_HOST=127.0.0.1`).

**Test:** `test_websocket_needs_access`, `test_websocket_needs_same_origin`, `test_websocket_closed_when_sharing_stops`, `test_discovery_does_not_announce_secrets`.

### 2.15 Accept or reject can't be bypassed

**What could happen:** a connected phone skips the "Accept / Reject" prompt by calling the upload API directly, reuses an approval to send other files, or uses another phone's approval.

**Protection:**
- With "Ask before receiving files" on (the default), every upload from another device must name an **accepted** transfer request. The server checks the exact folder, cleaned name, and size against the accepted list.
- An approval belongs to the device that asked (device ID cookie, 2.1); other devices get `404`/`403`.
- Each accepted file can be uploaded **once**. Resuming the same unfinished upload is allowed.
- Only the PC can accept or reject, a decision can't be changed, and unanswered requests expire after 2 minutes.
- Unfinished uploads belong to one device and one exact file (folder, name, size, and modified time).

**Test:** `test_upload_without_approval_is_refused`, `test_pending_request_cannot_upload`, `test_accepted_files_can_be_uploaded_once`, `test_another_device_cannot_use_an_approval`, `test_rejected_request`, `test_phone_cannot_accept_its_own_request`, `test_folder_request_matches_cleaned_names`.

### 2.16 Private data stored on the PC

**What could happen:** settings, history, or the HTTPS private key end up somewhere other devices can download them.

**Protection:**
- FileSh keeps its own data in `%LOCALAPPDATA%\FileSh` (settings, history, thumbnails, certificate and key, and the log when there is no console). That folder can never be shared (2.13).
- History is visible only on the PC and can be cleared there. Shared text is kept in memory only and is gone after a restart.
- The log file is limited to about 5 MB and never contains the token or PIN (2.11).

### 2.17 Bad images and the tray

**What could happen:** a "decompression bomb" image (small file, billions of pixels) uses all memory when making a thumbnail. Or "Start with Windows" runs something other than FileSh.

**Protection:**
- Thumbnails are made with Pillow with a pixel limit, where the warning for huge images is treated as an error; such images simply get no thumbnail.
- "Start with Windows" writes only FileSh's own command (the `.exe`, or `pythonw` with `FileSh.pyw`) to the current user's `Run` key; no administrator rights are needed or used.
- PowerShell (for the network check) is started by its full path, so a fake `powershell.exe` elsewhere on the PATH is never run.

**Test:** `test_thumbnail_of_broken_image`, `test_start_with_windows`.

---

## 3. Security checklist per version

A ticked item is built and covered by the automated tests above.

### Version 1
- [x] 2.1 Access token, cookie, `compare_digest`
- [x] 2.2 `safe_path()` helper used by every route, with attack tests
- [x] 2.3 Upload file name cleaning
- [x] 2.4 Host and Origin checks
- [x] 2.5 QR code shown only on the PC
- [x] 2.6 `textContent` only, downloads as attachment
- [x] 2.7 Disk space check, max file size, upload limit
- [x] 2.8 Security headers middleware
- [x] 2.9 Public network warning, firewall rule for Private only
- [x] 2.10 New token every start, **Stop sharing** button
- [x] 2.11 Safe errors and logs
- [x] 2.12 Pinned versions, `pip-audit` clean

### Version 2
- [x] PIN with attempt limit and temporary block (2.1)
- [x] Folder uploads: clean **every** folder name in the path, not only the file name (2.3)
- [x] Folder ZIP downloads: skip symlinks and junctions (2.2)
- [x] Accept / reject cannot be bypassed by calling the API directly (2.15)

### Version 3
- [x] Previews only for safe types; no `html`, `svg`, `xml`, `pdf` inline (2.6)
- [x] WebSocket connections also check the token and the Origin (2.14)
- [x] Clipboard/text sharing shows text with `textContent` and has a size limit (100 KB) (2.6, 2.7)
- [x] History only on the PC, stored outside the shared folder (2.16)

### Version 4
- [x] HTTPS with a self-signed certificate (2.9)
- [x] Resume uploads: check the partial file belongs to the same device and file (2.15)
- [x] Auto-stop after inactivity (2.10)
- [x] mDNS discovery does not broadcast the token (2.14)
- [x] The shared folder can't be set to system folders or whole drives (2.13)

---

## 4. How to check before each release

1. Run the tests: `pytest` (includes every test named in section 2).
2. Run `pip-audit -r requirements.txt -r requirements-dev.txt`.
3. In Claude Code, run **`/security-review`** to have the changes reviewed.
4. Do the manual tests from section 2 with a real phone: QR code, PIN, Accept / Reject, Stop sharing, HTTPS.
5. Only then mark the version as **done** in [features.md](features.md).
