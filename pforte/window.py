"""Ein eigenes Programmfenster mit GTK und WebKit (Linux), ohne Zusatzpakete.

Auf Mint, Ubuntu und Debian liegen ``python3-gi`` und WebKit2GTK meist schon
auf dem Rechner. Fehlt eines davon, nimmt der Starter ein App-Fenster von
Chrome/Edge und zuletzt den Browser.
"""

import os
from urllib.parse import urlparse

from . import NAME

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

try:
    import gi
    gi.require_version("Gdk", "3.0")
    gi.require_version("Gtk", "3.0")
    gi.require_version("WebKit2", "4.1")
    from gi.repository import Gdk, Gio, Gtk, WebKit2
except (ImportError, ValueError):
    Gtk = None


def available():
    return Gtk is not None and bool(os.environ.get("DISPLAY")
                                    or os.environ.get("WAYLAND_DISPLAY"))


def run(url, on_close=None):
    """Das Fenster öffnen und blockieren, bis es geschlossen wird."""
    window = Gtk.Window(title=NAME)
    window.set_default_size(1040, 780)
    window.set_position(Gtk.WindowPosition.CENTER)
    icon = os.path.join(HERE, "icon.png")
    if os.path.isfile(icon):
        try:
            window.set_icon_from_file(icon)
        except Exception:  # noqa: BLE001 - ein fehlendes Symbol ist kein Grund
            pass

    view = WebKit2.WebView()
    settings = view.get_settings()
    settings.set_enable_developer_extras(False)
    settings.set_enable_write_console_messages_to_stdout(False)
    background = Gdk.RGBA()
    background.parse("#0a0c13")          # kein weißes Aufblitzen vor dem Laden
    view.set_background_color(background)

    def decide(_view, decision, kind):
        """Links nach außen (Hosts öffnen) gehören in den richtigen Browser."""
        if kind in (WebKit2.PolicyDecisionType.NAVIGATION_ACTION,
                    WebKit2.PolicyDecisionType.NEW_WINDOW_ACTION):
            uri = decision.get_navigation_action().get_request().get_uri()
            if urlparse(uri).hostname not in ("127.0.0.1", "localhost"):
                Gio.AppInfo.launch_default_for_uri(uri, None)
                decision.ignore()
                return True
        return False

    view.connect("decide-policy", decide)
    window.add(view)
    window.connect("destroy", Gtk.main_quit)
    view.load_uri(url)
    window.show_all()
    Gtk.main()
    if on_close:
        on_close()
