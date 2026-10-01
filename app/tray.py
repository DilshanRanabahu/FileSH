"""Tray icon next to the Windows clock."""

import threading
import webbrowser

import pystray
from PIL import Image, ImageDraw

from app import desktop


def make_icon_image(size: int = 64) -> Image.Image:
    """The FileSh icon: a blue rounded square with a white arrow (same as the favicon)."""
    scale = size / 32
    image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((0, 0, size - 1, size - 1), radius=round(8 * scale), fill="#2563EB")
    width = max(2, round(2.5 * scale))
    points = [(10 * scale, 18 * scale), (16 * scale, 12 * scale), (22 * scale, 18 * scale)]
    draw.line(points, fill="white", width=width, joint="curve")
    draw.line([(16 * scale, 12 * scale), (16 * scale, 23 * scale)], fill="white", width=width)
    return image


def start_tray(runner) -> pystray.Icon:
    def open_page() -> None:
        webbrowser.open(runner.local_url)

    def sharing_on(item: pystray.MenuItem) -> bool:
        return bool(runner.ctx and runner.ctx.access.sharing)

    def toggle_sharing() -> None:
        if runner.ctx is not None:
            runner.submit(runner.ctx.set_sharing(not runner.ctx.access.sharing))

    def open_folder() -> None:
        desktop.open_in_explorer(runner.settings.shared_dir)

    def starts_with_windows(item: pystray.MenuItem) -> bool:
        return desktop.start_with_windows_enabled()

    def toggle_start_with_windows() -> None:
        desktop.set_start_with_windows(not desktop.start_with_windows_enabled())
        icon.update_menu()

    def quit_app() -> None:
        icon.stop()
        runner.quit()

    menu = pystray.Menu(
        pystray.MenuItem("Open FileSh", open_page, default=True),
        pystray.MenuItem("Sharing on", toggle_sharing, checked=sharing_on),
        pystray.MenuItem("Open shared folder", open_folder),
        pystray.MenuItem(
            "Start with Windows", toggle_start_with_windows, checked=starts_with_windows
        ),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Quit FileSh", quit_app),
    )
    icon = pystray.Icon("FileSh", make_icon_image(64), "FileSh", menu)

    def sharing_changed(sharing: bool) -> None:
        icon.title = "FileSh" if sharing else "FileSh (sharing stopped)"
        icon.update_menu()

    runner.notify = lambda message: icon.notify(message, "FileSh")
    runner.on_sharing_changed = sharing_changed
    threading.Thread(target=icon.run, name="tray", daemon=True).start()
    return icon
