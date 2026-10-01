<p align="center">
  <img src="docs/images/banner.svg" alt="FileSh: PC and phone file sharing over your own Wi-Fi" width="100%">
</p>

<p align="center">
  Share files, folders, and text between your Windows PC and your phone over your home Wi‑Fi.<br>
  No app on the phone, no internet, no cloud: the phone just opens a page in its browser.
</p>

<p align="center">
  <img alt="Python 3.12" src="https://img.shields.io/badge/Python-3.12-3776AB?style=for-the-badge&logo=python&logoColor=white">
  <img alt="FastAPI" src="https://img.shields.io/badge/FastAPI-009688?style=for-the-badge&logo=fastapi&logoColor=white">
  <img alt="JavaScript" src="https://img.shields.io/badge/JavaScript-no%20framework-F7DF1E?style=for-the-badge&logo=javascript&logoColor=black">
  <img alt="Windows" src="https://img.shields.io/badge/Windows-10%20%7C%2011-0078D6?style=for-the-badge&logo=windows&logoColor=white">
</p>

<p align="center">
  <img alt="Local network only" src="https://img.shields.io/badge/network-local%20only-2563EB?style=flat-square">
  <img alt="No phone app needed" src="https://img.shields.io/badge/phone%20app-not%20needed-16A34A?style=flat-square">
  <img alt="Last commit" src="https://img.shields.io/github/last-commit/DilshanRanabahu/FileSH?style=flat-square">
  <img alt="Code size" src="https://img.shields.io/github/languages/code-size/DilshanRanabahu/FileSH?style=flat-square">
  <img alt="Top language" src="https://img.shields.io/github/languages/top/DilshanRanabahu/FileSH?style=flat-square">
</p>

## Start FileSh

**From the `.exe`:** double-click `dist\FileSh.exe` (build it first with `scripts\build.ps1`). FileSh opens in your browser and adds an icon next to the clock.

**From the source code:**

```powershell
.venv\Scripts\Activate.ps1
python -m app.main
```

The first time, Windows asks whether FileSh may use the network: allow it on **Private networks** only.

## Connect your phone

1. Make sure your phone and PC are on the same network, and that Windows calls the network **Private** (Settings → Network & internet → your connection → Network profile type).
2. Scan the **QR code** on the PC page with your phone's camera.
   Or open the address shown on the PC (for example `192.168.1.10:8000`), or `filesh.local:8000`, and type the **PIN**.

## What you can do

- **Files tab:** send files or whole folders from the phone; download files, or whole folders as a ZIP. On the PC you can drag and drop. Photos show thumbnails; tap a photo, video, or song to preview it.
- **Accept / Reject:** when a phone sends files, the PC asks first (you can switch this off in Settings).
- **Text tab:** send text or a link to every connected device, then copy it.
- **History tab** (PC): what was sent and received.
- **Settings tab** (PC): shared folder, auto-stop, HTTPS encryption, `filesh.local`, start with Windows.
- **Stop sharing** disconnects every device at once. Sharing also stops by itself after 30 minutes with no device connected.

Interrupted uploads continue where they stopped. Everything stays on your local network.

## Where things are

- Shared folder: `shared\` in this project, or `C:\Users\<you>\FileSh` when using the `.exe` (change it in Settings).
- FileSh's own settings, history, and log: `%LOCALAPPDATA%\FileSh`.

## For developers

See [AGENTS.md](AGENTS.md) (setup, commands, structure, rules), [docs/features.md](docs/features.md), [docs/design.md](docs/design.md), and [docs/SECURITY.md](docs/SECURITY.md).
