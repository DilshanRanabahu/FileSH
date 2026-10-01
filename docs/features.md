# FileSh: Features

FileSh is a local file and folder sharing app. The PC runs a small web server, and any device on the same Wi‑Fi or wired network (phone, tablet, laptop) connects through a web browser. No app needs to be installed on the phone.

**Tech stack:** Python 3.12, FastAPI + Uvicorn, plain HTML/CSS/JavaScript, PyInstaller for packaging. Details in [AGENTS.md](../AGENTS.md).

Build one version at a time. Each version should work fully before starting the next.

**Security:** each version also has a security checklist in [SECURITY.md](SECURITY.md#3-security-checklist-per-version). A version is done only when its features **and** its security checks are complete.

**How to read the boxes:** a ticked box means the feature is built and passes the automated tests (`pytest`) and the browser test. A version is only **done** after the manual test with a real phone ([SECURITY.md section 4](SECURITY.md#4-how-to-check-before-each-release)).

---

## Version 1: Core

**Status:** built and tested. Waiting for a real-phone test.

- [x] **Upload files from phone to PC.** Select several files at once.
- [x] **Download files from PC to phone.** Browse the shared folder and tap a file to download it.
- [x] **Progress bar.** Show percent, speed (MB/s), and time remaining.
- [x] **QR code connect.** The PC shows a QR code containing its local IP address; scanning it opens the app on the phone.
- [x] **Large file support.** Stream files in chunks so 5–10 GB files work without filling RAM.
- [x] **Mobile-friendly page.** Large buttons and a layout that works well on small screens.
- [x] **Auto-refresh file list.** If the live connection (Version 3) is down, each page checks its open folder every 3 seconds instead. Paused while the page is hidden.
- [x] **Access token.** A new random token at every start, included in the QR code link. Devices without it cannot connect.
- [x] **Stop sharing button.** One click on the PC page closes access for all devices.
- [x] **Public network warning.** Warn when Windows reports the network as Public.

## Version 2: Folders and security

**Status:** built and tested. Waiting for a real-phone test.

- [x] **Download a whole folder as a ZIP.** The ZIP is created on the fly while downloading. Each folder row has a ZIP button, and the current folder has one next to Refresh.
- [x] **Upload folders.** "Choose a folder" works in Android Chrome and desktop browsers; on iPhone, the button is hidden and the user selects multiple files instead.
- [x] **PIN connect.** A 6-digit PIN for devices that cannot scan the QR code, with 5 attempts and then a 5-minute block.
- [x] **Accept or reject on the PC.** A prompt asks "Android phone wants to send: photo.jpg (2.4 MB)". Can be switched off in Settings.
- [x] **Safe file names.** Never overwrite: if `photo.jpg` exists, save the new file as `photo (1).jpg`. Block unsafe paths such as `../`.

## Version 3: Better experience

**Status:** built and tested. Waiting for a real-phone test.

- [x] **Drag and drop on the PC page.** Drop files or whole folders anywhere on the Files tab.
- [x] **Text and clipboard sharing.** A Text tab: send text or a link from any device; it appears on all devices with a Copy button.
- [x] **Instant live updates.** A WebSocket pushes changes (new files, text, transfer requests, devices) immediately, including files copied into the folder with Explorer.
- [x] **Image and video preview.** Image thumbnails in the file list; tap an image, video, or audio file to view or play it, with previous and next buttons.
- [x] **Transfer history.** A History tab (PC only) listing sent and received files with device, size, and time, stored in a JSON file.
- [x] **Dark mode.** Follows the device setting, with a sun/moon button to switch.

## Version 4: Advanced

**Status:** built and tested. Waiting for a real-phone test.

- [x] **Resume interrupted transfers.** Uploads continue from the last byte after the connection drops, retrying by themselves. Downloads can be resumed by the browser.
- [x] **Multiple devices.** Several phones, tablets, or laptops connected at the same time; click "N devices online" on the PC to see them.
- [x] **Automatic device discovery.** The PC answers to `filesh.local` (mDNS); open `http://filesh.local:8000` and enter the PIN. Works on iPhone, Mac, and Windows; some Android phones don't support it.
- [x] **HTTPS encryption.** Optional (Settings). Uses a self-signed certificate; phones then connect on port 8001 and show a one-time warning.
- [x] **Auto-stop.** Stop sharing after 15, 30 (default), 60, or 120 minutes with no device connected, or never.
- [x] **System tray app and `.exe`.** Runs in the tray with a menu (open, sharing on/off, open folder, start with Windows, quit). `scripts\build.ps1` builds `dist\FileSh.exe`.
- [x] **Choose the save folder.** On the Settings page, with the Windows folder picker. System folders and whole drives are refused.

---

## Out of scope

These features are intentionally left out:

- **User accounts and login.** Too complex for a local app; a token or PIN is enough.
- **Internet or cloud sharing.** That is a different project that needs a public server and stronger security.
- **A database.** The file system stores the files; a simple JSON file is enough for history and settings.
- **Video thumbnails.** They need a video decoder such as FFmpeg; videos show an icon and play in the preview instead.

---

## Setup notes (Windows)

- Set the network profile to **Private** (Settings → Network & internet → Ethernet or Wi‑Fi → Network profile type). On **Public**, Windows Firewall blocks other devices.
- Allow FileSh through Windows Firewall for the **Private** profile only, never Public. FileSh prints the exact commands when it starts.
- Make sure the router's **AP isolation** (client isolation) is off, and don't use the guest network.
