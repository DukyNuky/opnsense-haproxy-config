"""A small window that says how far the reading has come.

It sits over the main window and takes the clicks, so that "nothing can be
used right now" is true rather than merely looked like. One bar in the whole
program: two of them in two corners said the same thing twice, and neither
said that.

It must never be able to lock the program up. A host that answers neither yes
nor no and never times out would otherwise leave this window standing for
good, so there is a button that puts it away while the reading carries on
behind it -- and closing it through the window manager does the same.
"""

import tkinter as tk
from tkinter import ttk


class Progress:
    """The one progress window, built on first use and reused after that."""

    def __init__(self, app):
        self.app = app
        self.window = None

    @property
    def showing(self):
        return self.window is not None and self.window.winfo_exists()

    def show(self, title="Systeme werden gelesen"):
        if self.showing:
            self.heading.configure(text=title)
            return
        app = self.app
        self.window = window = tk.Toplevel(app)
        window.title("Bitte warten")
        window.transient(app)
        window.resizable(False, False)
        window.configure(bg=app.colors["bg"])
        window.protocol("WM_DELETE_WINDOW", self.hide)
        window.columnconfigure(0, weight=1)

        card = ttk.Frame(window, style="Card.TFrame", padding=(24, 20))
        card.grid(row=0, column=0, sticky="nsew")
        card.columnconfigure(0, weight=1)

        self.heading = ttk.Label(card, text=title, style="H2.TLabel")
        self.heading.grid(row=0, column=0, sticky="w")
        self.count = ttk.Label(card, text="", style="Hint.TLabel")
        self.count.grid(row=1, column=0, sticky="w", pady=(4, 12))
        self.bar = ttk.Progressbar(card, mode="determinate", length=380,
                                   style="Bar.Horizontal.TProgressbar")
        self.bar.grid(row=2, column=0, sticky="ew")
        self.waiting = ttk.Label(card, text="", style="Hint.TLabel",
                                 wraplength=380, justify="left")
        self.waiting.grid(row=3, column=0, sticky="w", pady=(12, 0))
        ttk.Button(card, text="Im Hintergrund weiterlesen",
                   style="Ghost.TButton", command=self.hide).grid(
            row=4, column=0, sticky="e", pady=(16, 0))

        window.update_idletasks()
        self._centre()
        # The clicks go here and nowhere else, which is what makes the window
        # behind it plainly not usable without greying anything out. Not taken
        # while something else holds the grab: a settings dialog that is open
        # would lose it here and never get it back.
        if app.grab_current() is None:
            try:
                window.grab_set()
            except tk.TclError:
                pass  # not mapped yet; the window is still perfectly readable

    def _centre(self):
        app, window = self.app, self.window
        width, height = window.winfo_reqwidth(), window.winfo_reqheight()
        if app.winfo_width() <= 1:
            # the very first reading starts before the main window has been
            # given a size; let the window manager place this one
            window.geometry(f"{width}x{height}")
            return
        x = app.winfo_rootx() + (app.winfo_width() - width) // 2
        y = app.winfo_rooty() + (app.winfo_height() - height) // 3
        window.geometry(f"{width}x{height}+{max(x, 0)}+{max(y, 0)}")

    def step(self, done, total, waiting=()):
        """How far along, and which systems are still out."""
        if not self.showing:
            return
        self.bar.configure(maximum=max(total, 1), value=done)
        self.count.configure(text=f"{done} von {total} gelesen")
        names = list(waiting)
        self.waiting.configure(
            text=("noch offen: " + ", ".join(names[:4])
                  + (f" und {len(names) - 4} weitere" if len(names) > 4 else ""))
            if names else "gleich fertig")

    def hide(self):
        if not self.showing:
            self.window = None
            return
        try:
            self.window.grab_release()
        except tk.TclError:
            pass  # the grab may already be gone with the window
        self.window.destroy()
        self.window = None

    def apply_theme(self):
        if self.showing:
            self.window.configure(bg=self.app.colors["bg"])
