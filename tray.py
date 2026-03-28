"""
System tray icon for PACS Admin Tool.

Provides a taskbar tray icon with a right-click menu for both the
desktop GUI and the headless web server.  Uses pystray + Pillow.
"""

import os
import sys
import threading
import logging

try:
    import pystray
    from PIL import Image
except ImportError:
    raise ImportError(
        "pystray and Pillow are required for system tray support. "
        "Install them with: pip install pystray Pillow"
    )

logger = logging.getLogger(__name__)


def _icon_path() -> str:
    """Return the absolute path to icon.png, handling PyInstaller bundles."""
    if getattr(sys, "frozen", False):
        base = sys._MEIPASS
    else:
        base = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base, "icon.png")


def _load_icon_image() -> Image.Image:
    """Load the tray icon image, falling back to a generated one."""
    path = _icon_path()
    try:
        return Image.open(path)
    except Exception:
        logger.warning("Could not load icon from %s; using fallback", path)
        # 16x16 solid blue square as a minimal fallback
        return Image.new("RGB", (64, 64), color=(43, 108, 176))


class TrayIcon:
    """
    A system-tray icon that runs in its own thread.

    Parameters
    ----------
    tooltip : str
        Hover text shown next to the tray icon.
    menu_items : list[tuple[str, callable]]
        List of (label, callback) pairs for the right-click menu.
        A ``None`` entry inserts a separator.
    on_quit : callable
        Called when the user clicks "Exit" in the tray menu.
        This should trigger a clean shutdown of the application.
    on_double_click : callable | None
        Optional callback when the user double-clicks the tray icon.
    """

    def __init__(self, tooltip, menu_items, on_quit, on_double_click=None):
        self._tooltip = tooltip
        self._menu_items = menu_items
        self._on_quit = on_quit
        self._on_double_click = on_double_click
        self._icon = None
        self._thread = None

    def start(self):
        """Create the tray icon and start it in a background thread."""
        image = _load_icon_image()

        # Build pystray menu
        items = []
        for entry in self._menu_items:
            if entry is None:
                items.append(pystray.Menu.SEPARATOR)
            else:
                label, callback = entry
                # Mark the first item as default (activated on double-click)
                is_default = (entry == self._menu_items[0])
                items.append(pystray.MenuItem(label, callback, default=is_default))

        items.append(pystray.Menu.SEPARATOR)
        items.append(pystray.MenuItem("Exit", self._quit))

        self._icon = pystray.Icon(
            name="pacs_admin_tool",
            icon=image,
            title=self._tooltip,
            menu=pystray.Menu(*items),
        )

        self._thread = threading.Thread(target=self._icon.run, daemon=True)
        self._thread.start()
        logger.info("System tray icon started")

    def stop(self):
        """Remove the tray icon."""
        if self._icon is not None:
            try:
                self._icon.stop()
            except Exception:
                pass
            logger.info("System tray icon stopped")

    def _quit(self, icon, item):
        """Handle the Exit menu click."""
        self.stop()
        if self._on_quit:
            self._on_quit()
