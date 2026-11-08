"""Fenster öffnen: bevorzugt als eigenes App-Fenster, sonst im Browser."""

import os
import shutil
import subprocess
import sys
import webbrowser

from . import NAME, config
from .server import App, make_server, watch_window


def app_browsers():
    """Browser, die eine Adresse als eigenes Fenster ohne Leisten öffnen."""
    names = ("google-chrome", "google-chrome-stable", "chromium",
             "chromium-browser", "microsoft-edge", "microsoft-edge-stable",
             "brave-browser")
    found = [path for path in map(shutil.which, names) if path]
    if os.name == "nt":
        roots = [os.environ.get(v) for v in
                 ("PROGRAMFILES", "PROGRAMFILES(X86)", "LOCALAPPDATA")]
        for root in filter(None, roots):
            for rel in (r"Microsoft\Edge\Application\msedge.exe",
                        r"Google\Chrome\Application\chrome.exe"):
                path = os.path.join(root, rel)
                if os.path.isfile(path):
                    found.append(path)
    elif sys.platform == "darwin":
        for path in ("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
                     "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge"):
            if os.path.isfile(path):
                found.append(path)
    return found


def open_window(url):
    for browser in app_browsers():
        profile = os.path.join(config.config_dir(), "fenster")
        try:
            subprocess.Popen([browser, f"--app={url}", "--window-size=1040,760",
                              f"--user-data-dir={profile}", "--no-first-run",
                              "--no-default-browser-check"],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return True
        except OSError:
            continue
    return webbrowser.open(url)


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    port = 0
    show = "--no-window" not in argv
    for arg in argv:
        if arg.startswith("--port="):
            port = int(arg.split("=", 1)[1])
    app = App()
    server = make_server(app, port)
    real = server.server_address[1]
    url = f"http://127.0.0.1:{real}/?t={app.token}"
    print(f"{NAME} läuft auf http://127.0.0.1:{real}/ — Fenster schließen beendet das Programm.")
    if show:
        if not open_window(url):
            print(f"Bitte diese Adresse im Browser öffnen:\n  {url}")
        watch_window(app, server)
    else:
        print(f"  {url}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0
