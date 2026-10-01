# FileSh: UI Design

The goal is a **clean, simple, and calm** interface. It should look tidy and professional without being fancy or colourful: mostly white or grey, with **one accent colour (blue)** used only for important actions.

See [features.md](features.md) for the feature list and [SECURITY.md](SECURITY.md) for security rules that affect the UI.

**Technical rule:** all CSS and JavaScript go in separate files under `app/static/` (`style.css`, `js/*.js`). No inline `<script>`, `style=""`, or `on...=` attributes, because the security policy blocks them.

---

## 1. Design principles

1. **Simple first.** Each screen has one main action that is easy to find.
2. **One accent colour.** Blue is used only for main buttons, links, the selected tab, and progress. Everything else is neutral grey.
3. **Phone first.** Design for a phone screen, then widen the layout for the PC.
4. **Clear feedback.** The user always knows what is happening: waiting, uploading, done, or failed.
5. **No decoration.** No gradients, heavy shadows, animations for show, or background images.

---

## 2. Colours

Colours are defined as CSS variables, so dark mode only swaps the values.

### Light mode

| Token | Hex | Used for |
|---|---|---|
| `--bg` | `#F6F7F9` | Page background |
| `--surface` | `#FFFFFF` | Cards, file list, dialogs |
| `--border` | `#E3E6EA` | Card borders, dividers |
| `--text` | `#1F2933` | Main text |
| `--text-muted` | `#6B7280` | File sizes, dates, hints |
| `--accent` | `#2563EB` | Main buttons, links, progress bar, selected tab |
| `--accent-hover` | `#1D4ED8` | Button hover/pressed |
| `--accent-soft` | `#EFF4FF` | Row hover, drop-zone highlight |
| `--on-accent` | `#FFFFFF` | Text on accent buttons |
| `--success` | `#16A34A` | "Done", received files |
| `--warning` | `#D97706` | Warnings, public network banner |
| `--danger` | `#DC2626` | Errors, Delete and Stop |

### Dark mode

Dark mode follows the device setting. The sun/moon button in the header switches between light and dark, and the choice is remembered on that device.

| Token | Hex |
|---|---|
| `--bg` | `#111418` |
| `--surface` | `#1A1F25` |
| `--border` | `#2A313A` |
| `--text` | `#E6E8EB` |
| `--text-muted` | `#9AA3AE` |
| `--accent` | `#60A5FA` |
| `--accent-hover` | `#93C5FD` |
| `--accent-soft` | `#1B2A40` |
| `--on-accent` | `#111418` |
| `--success` | `#4ADE80` |
| `--warning` | `#FBBF24` |
| `--danger` | `#F87171` |

In dark mode, cards have no shadow, and the QR code always stays on a white background so phones can scan it.

### Colour rules

- Use the **accent** colour for no more than one or two elements per screen.
- Status colours (success, warning, danger) appear only in messages, icons, and progress bars, never as large backgrounds.
- Text must have a contrast ratio of at least **4.5:1** against its background.

---

## 3. Typography

Use the system font: it loads instantly, works offline, and looks native on every device.

```css
font-family: system-ui, -apple-system, "Segoe UI", Roboto, sans-serif;
```

| Style | Size | Weight | Used for |
|---|---|---|---|
| Title | 20px | 600 | Page title ("FileSh"), message screens |
| Heading | 16px | 600 | Section titles ("Shared files") |
| Body | 15px | 400 | File names, normal text |
| Small | 13px | 400 | File size, date, hints |

- Line height: **1.5**.
- Cut long file names with `…` in the middle so the extension stays visible: `holiday_photo…_2026.jpg`. The full name shows on hover.

---

## 4. Spacing and shape

- **Spacing scale:** 4, 8, 12, 16, 24, 32px. Use only these values.
- **Page padding:** 16px on phone, 24px on PC.
- **Border radius:** 8px for buttons and inputs, 12px for cards.
- **Shadows:** at most one soft shadow on cards: `0 1px 2px rgba(0,0,0,0.06)`. Prefer borders.
- **Max content width on PC:** 960px, centred.

---

## 5. Icons

- **Line icons** from [Lucide](https://lucide.dev) only, stored in `app/static/icons.svg` and used as `<use href="/static/icons.svg#name">`, so they work offline.
- Size 20px, colour `--text-muted` (or `--accent` for actions like download and open).
- File-type icons: folder, image, video, audio, document, archive, and a generic file icon. Images show a **thumbnail** instead.

---

## 6. Components

### Buttons

| Type | Look | Used for |
|---|---|---|
| **Primary** | Accent background, `--on-accent` text | The main action: "Send files", "Accept" |
| **Secondary** | Surface background, grey border | "Cancel", "Reject", "Browse…" |
| **Danger** | Red text, no background | "Delete", "Stop", "Stop sharing" |
| **Icon button** | Icon only, 44×44px touch area | Refresh, download, theme |
| **Small** | 36px tall, 13px text | Actions inside rows ("Copy", "Clear all") |

- Minimum height **44px** (small: 36px inside rows) so buttons are easy to tap.
- Disabled buttons use 50% opacity.

### Tabs

- Below the header on the right column: **Files** and **Text** for everyone; **History** and **Settings** on the PC only.
- Icon + label. The selected tab has accent text and a 2px accent underline; others are muted.
- Arrow keys move between tabs. The last tab is remembered on that device.

### Upload area (drop zone)

- A dashed grey border box with an upload icon and the text **"Tap to choose files"** (phone) or **"Drag files here or click to choose"** (PC).
- On hover, or while files are dragged over the page: border turns accent and background becomes `--accent-soft`.
- Below it: **Choose a folder** (secondary; hidden on iPhone, which can't pick folders) and **Clear** (only when something is selected).
- The selection shows as muted text in the box: `Trip · 25 files · 120 MB`.
- Dropped files are sent straight away; chosen files are sent with **Send files**.

### File list

```
[icon/thumb]  file-name.jpg                        [⬇]
              2.4 MB · Today, 14:32
[folder]      Photos                          ›    [⇩zip]
              Folder · Today, 14:32
```

- Rows are 56px tall with a thin divider between them.
- Folders first, then files, sorted by name.
- Tapping a folder opens it; a **breadcrumb** at the top shows the path: `Shared › Photos › 2026`.
- Tapping an image, video, or audio file opens the **preview**; other files download.
- The button on the right downloads the file, or the folder as a ZIP. The section header has a ZIP button for the open folder and a Refresh button.
- Image thumbnails are 40×40px with 6px rounded corners, loaded only when visible.

### Progress item

```
[icon]  video.mp4                            45%
        ███████████░░░░░░░░░░░░░
        120 MB of 266 MB · 11.2 MB/s · 13 s left   [Cancel]
```

- Bar height 6px, accent fill on a grey track, rounded ends.
- **Waiting for the PC:** full bar at 30% opacity, text "Waiting for the PC to accept…", **Cancel**.
- **Connection lost:** text "Connection lost. Trying again in 8 s…"; it continues from where it stopped.
- **Done:** bar turns green, text says **"Done"**, the row disappears after 5 seconds.
- **Failed:** bar turns red, text shows the reason, with **Retry** and **Remove**.

### Form fields

- **Text field / text area:** 44px tall, 1px border, 8px radius; the border turns accent on focus.
- **Switch:** 44×26px pill; grey when off, accent when on. Each switch sits on a row with a bold label and a muted one-line explanation.
- **Select:** same look as a text field.

### Toast messages

- Small message at the bottom of the screen for 3 seconds: "3 files sent", "Copied", "Sharing stopped".
- Surface card with a coloured icon on the left (green/amber/red). Never a fully coloured background.

### Dialogs

All dialogs: surface card, 12px radius, 24px padding, dimmed backdrop, buttons on the right.

**Incoming files (PC)**

```
┌─────────────────────────────────┐
│  Incoming files                 │
│                                 │
│  Android phone wants to send:   │
│  • photo.jpg (2.4 MB)           │
│  • notes.pdf (310 KB)           │
│  and 23 more. Total: 25 files,  │
│  120 MB                         │
│                                 │
│          [Reject]  [Accept]     │
└─────────────────────────────────┘
```

- Shows up to 5 names. Esc does not close it; the user must answer. The tab title shows the number waiting: `(1) FileSh`.

**Confirm** (Stop sharing, Clear history, Clear all text): title, one sentence, **Cancel** and a danger button.

**Connected devices (PC):** opened by clicking "N devices online"; each row shows a phone icon, the device name, its IP address, and how long it has been connected.

**Preview:** up to 960px wide. Header: file name, Download, Close. Body: the image, or a video/audio player. Footer: ‹ `2 of 7` › to move between previewable files (also with the arrow keys).

---

## 7. Screens

### 7.1 Phone: main screen

```
┌──────────────────────────────┐
│ FileSh            ● Online ☾ │  ← name, connection status, theme
├──────────────────────────────┤
│  Files   Text                │  ← tabs
│ ┌──────────────────────────┐ │
│ │           ⬆              │ │
│ │   Tap to choose files    │ │  ← upload area
│ └──────────────────────────┘ │
│  [ Choose a folder ]         │
│  [        Send files       ] │  ← primary button
│                              │
│ Uploading                    │  ← only while active
│  video.mp4            45%    │
│  ███████░░░░░░░░░            │
│                              │
│ Shared files          ⇩  ⟳   │
│  Shared › Photos             │  ← breadcrumb
│  📁 2026               ›  ⇩  │
│  🖼 beach.jpg  2.4 MB     ⬇  │  ← thumbnail, download
└──────────────────────────────┘
```

### 7.2 PC: main screen

The PC opens the same page in its browser. On wide screens, the layout uses two columns.

```
┌──────────────────────────────────────────────────────────────┐
│ FileSh                                 ● 2 devices online  ☾ │
├───────────────────────┬──────────────────────────────────────┤
│  Connect a device     │  Files   Text   History   Settings   │
│  ┌─────────────────┐  │  ┌────────────────────────────────┐  │
│  │                 │  │  │ Drag files here or click to    │  │
│  │    QR CODE      │  │  │ choose                         │  │
│  │                 │  │  └────────────────────────────────┘  │
│  └─────────────────┘  │  Shared files                 ⇩  ⟳  │
│  Scan with your phone │  📁 2026                       ›  ⇩  │
│  or open:             │  🖼 beach.jpg     2.4 MB  Today   ⬇ │
│  192.168.1.10:8000    │                                      │
│  PIN 482 913          │                                      │
│  Or open filesh.local │                                      │
│  and enter the PIN.   │                                      │
│  [ Stop sharing ]     │                                      │
└───────────────────────┴──────────────────────────────────────┘
```

- Left column (280px): QR code, address (with `https://` when HTTPS is on), PIN, the `filesh.local` hint when discovery is on, and **Stop sharing**. It stays in view while scrolling.
- This panel is shown **only on the PC itself**. Other devices opening the same page never see it (see [SECURITY.md](SECURITY.md) 2.5).
- Below **768px** wide, the columns stack: the connect panel comes first, then the tabs.

### 7.3 Text tab

- Card "Share text": a 4-line text area ("Type or paste text or a link…") and a full-width **Send text** button (Ctrl+Enter also sends).
- Card "Recent": newest first. Each item shows the text (a single web link is clickable), then a muted line `Android phone · Today, 14:32` with **Copy** and **Delete**. **Clear all** in the card header.

### 7.4 History tab (PC only)

- One row per transfer: a green down-arrow for received or an accent up-arrow for sent, the file name, and `Received from iPhone · 2.4 MB · Today, 14:32`. **Clear** in the card header.

### 7.5 Settings tab (PC only)

- **Shared folder:** path field with **Browse…** (opens the Windows folder picker), **Save folder**, and **Open in Explorer**.
- **Receiving and sharing:** switches for "Ask before receiving files" and "Discoverable as filesh.local", and a select for "Stop sharing automatically" (Never, 15, 30, 60, 120 minutes).
- **Security:** "HTTPS encryption" switch, with the certificate fingerprint when HTTPS is running.
- **Windows:** "Start with Windows" switch.
- When a change needs a restart (HTTPS), an amber banner at the top says so with a **Restart now** button. While restarting, the page shows "Restarting FileSh…" and reloads by itself.

### 7.6 Empty and error states

| State | What the user sees |
|---|---|
| No files yet | Folder icon + "No files yet. Send something from your phone or PC." |
| No text / history yet | Icon + "No text yet." / "Files sent and received will be listed here." |
| Server not reachable | "Can't reach your PC. Check that FileSh is running and both devices are on the same network." + **Retry**. If the page was already open, the header just shows a red dot and "Offline". |
| No or old token | The **PIN screen** (7.7). |
| Sharing stopped (phone) | Lock icon, "Sharing is stopped", "Scan the new QR code when it is started again." |
| Upload failed | Red progress bar, reason, **Retry** and **Remove** |
| Not enough disk space | "Not enough space on the PC" |
| File too large | "This file is larger than the limit (20 GB)" |
| PC declined | Amber toast "The PC declined the files" |
| No answer from the PC | Amber toast "No answer from the PC. Open FileSh on the PC and try again." |

### 7.7 Security screens

**Public network warning (PC only).** An amber banner across the top of the PC page. It cannot be hidden while the network is Public.

```
┌──────────────────────────────────────────────────────────────┐
│ ⚠ You are on a public network. Other people may be able to  │
│   see your transfers. Use FileSh only on your home network.  │
└──────────────────────────────────────────────────────────────┘
```

- Surface background, 4px amber left border, amber icon, normal text colour.

**Stop sharing.** A secondary button with red text at the bottom of the connect panel, plus "Sharing on" in the tray menu. The confirm dialog says: "All connected devices will be disconnected. You will get a new QR code and PIN next time."

**Stopped screen (PC).** Lock icon, "Sharing is stopped", "Other devices can't connect. Your files stay on this PC.", and a primary **Start sharing** button. When auto-stop ends sharing, an amber toast says why.

**PIN entry (other devices).** Shown when a device opens the address without a valid token.

```
┌──────────────────────────────┐
│ FileSh                    ☾  │
├──────────────────────────────┤
│             🔒               │
│   Enter the PIN shown on     │
│   your PC                    │
│        [ 123 456 ]           │  ← one large field, 28px digits
│   [        Connect        ]  │
│   Wrong PIN. 4 attempts left │  ← red, only after a wrong PIN
│   Or scan the QR code on     │
│   your PC.                   │
└──────────────────────────────┘
```

- One field with the numeric keyboard (`inputmode="numeric"`), shown as `123 456` while typing.
- After too many wrong attempts: "Too many attempts. Try again in 5 minutes."

---

## 8. Responsive breakpoints

| Width | Layout |
|---|---|
| Below 768px | Phone: one column, full-width buttons |
| 768px and wider | PC/tablet: two columns (PC), content max 960px |

---

## 9. Accessibility

- Every icon button has a text label (`aria-label`), and tabs use `role="tab"` with `aria-selected`.
- Visible focus outline (2px `--accent`) for keyboard users.
- Never show status by colour alone: always add text or an icon ("Done", "Failed").
- Touch targets at least 44×44px.
- Respect `prefers-reduced-motion`: no animations for users who turn them off.

---

## 10. Motion

Keep animation minimal and functional:

- Buttons, tabs, rows, and switches: 150ms colour change.
- Progress bar: smooth width transition (200ms).
- Toasts: fade in and out (200ms).
- Nothing else moves.
