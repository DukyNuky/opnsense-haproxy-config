"""A cover over the window while there is nothing to be done with it.

Two progress bars in two places is one too many, and neither of them said the
thing that matters: right now, nothing here can be used. So the progress moved
into a panel laid over the window, and the window behind it goes quiet.

Real blur is not something tkinter can do -- there is no compositing between
widgets, and faking it would mean photographing the window, blurring the
picture and showing that instead, which costs more than it is worth. What
happens instead is a plain cover in the window's own background colour: the
content is gone rather than smeared, which reads as "not now" just as well.
"""

import tkinter as tk
from tkinter import ttk


class Curtain:
    """One panel over everything, with the only progress bar in the program.

    Built the first time it is needed and kept afterwards: a cover that has to
    be created before it can be shown is a cover that flickers.
    """

    def __init__(self, app):
        self.app = app
        self.frame = None
        self.showing = False

    def _build(self):
        colors = self.app.colors
        self.frame = tk.Frame(self.app, bg=colors["bg"])
        self.frame.columnconfigure(0, weight=1)
        self.frame.rowconfigure(0, weight=1)
        self.frame.rowconfigure(2, weight=1)

        card = ttk.Frame(self.frame, style="Card.TFrame", padding=(28, 24))
        card.grid(row=1, column=0)
        card.columnconfigure(0, weight=1)

        self.title = ttk.Label(card, text="", style="H2.TLabel")
        self.title.grid(row=0, column=0, sticky="w")
        self.count = ttk.Label(card, text="", style="Hint.TLabel")
        self.count.grid(row=1, column=0, sticky="w", pady=(4, 12))
        self.bar = ttk.Progressbar(card, mode="determinate", length=420,
                                   style="Bar.Horizontal.TProgressbar")
        self.bar.grid(row=2, column=0, sticky="ew")
        self.waiting = ttk.Label(card, text="", style="Hint.TLabel",
                                 wraplength=420, justify="left")
        self.waiting.grid(row=3, column=0, sticky="w", pady=(12, 0))

        # The way out. A host that never answers and never times out would
        # otherwise leave this cover lying over the window for good, and a
        # program that can lock itself up is worse than one that reads slowly.
        # The reading carries on behind it either way.
        ttk.Button(card, text="Im Hintergrund weiterlesen",
                   style="Ghost.TButton", command=self.hide).grid(
            row=4, column=0, sticky="e", pady=(16, 0))

        # Nothing behind the cover may be clicked, and nothing on it can be:
        # swallowing the events is what makes "nothing can be done" true
        # rather than merely looked like.
        for sequence in ("<Button-1>", "<Button-2>", "<Button-3>", "<Key>"):
            self.frame.bind(sequence, lambda _event: "break")

    def show(self, title="Einen Moment …"):
        if self.frame is None:
            self._build()
        self.title.configure(text=title)
        self.frame.place(relx=0, rely=0, relwidth=1, relheight=1)
        self.frame.lift()
        self.frame.focus_set()
        self.showing = True

    def step(self, done, total, waiting=()):
        """How far along, and what is still outstanding."""
        if not self.showing:
            return
        self.bar.configure(maximum=max(total, 1), value=done)
        self.count.configure(text=f"{done} von {total}")
        names = list(waiting)
        self.waiting.configure(
            text=("noch offen: " + ", ".join(names[:4])
                  + (f" und {len(names) - 4} weitere" if len(names) > 4 else ""))
            if names else "")

    def hide(self):
        if self.frame is not None and self.showing:
            self.frame.place_forget()
        self.showing = False

    def apply_theme(self):
        """The cover is the window's own background, so it follows the theme."""
        if self.frame is not None:
            self.frame.configure(bg=self.app.colors["bg"])
