"""Every system the program reads from, and the last answer each one gave.

One AdGuard, three AdGuards, two Docker hosts and an OPNsense are all the same
kind of thing from here: something that is asked, that takes a moment, that
answers or does not, and whose answer is worth keeping until it is asked
again. Each tab reads its own kind out of the same shelf, and the status tab
reads all of them without asking anybody anything.

Nothing here knows about windows. A refresh runs in threads and reports each
change through a callback; whoever holds a window is responsible for getting
that onto its own thread.
"""

import threading
import time

# What is known about one system at any moment. IDLE is not "broken" and not
# "empty" -- it is "nobody has asked yet", which the status tab has to be able
# to say out loud rather than showing an empty list that looks like an answer.
IDLE = "idle"
LOADING = "loading"
OK = "ok"
FAILED = "failed"


class Source:
    """One system, the way to ask it, and what it said the last time.

    ``read`` is called with no arguments in a worker thread and returns
    whatever the tab wants to show. Raising is a normal outcome: a host that
    is off is not a bug, and the message is kept to be shown beside it.
    """

    def __init__(self, kind, name, read, label="", settings=None):
        self.kind = kind
        self.name = name
        self.label = label or name
        # The entry this was built from. Kept because what was read is not
        # always enough on its own: whether a DNS name points at the right
        # place needs the address HAProxy sits on, and that is written in the
        # settings rather than in any answer.
        self.settings = dict(settings or {})
        self._read = read
        self.status = IDLE
        self.data = None
        self.error = ""
        self.read_at = 0.0
        self.took = 0.0
        # Counts finished reads. A tab that redraws on every notification uses
        # it to tell "answered again, same content" from "never answered".
        self.reads = 0

    def __repr__(self):
        return f"<Source {self.kind}/{self.name} {self.status}>"

    @property
    def ready(self):
        """Is there something to show, even if the last read failed?

        A failed refresh does not throw away what was read before it. Half an
        hour old and labelled as such beats an empty tab.
        """
        return self.data is not None

    def age(self, now=None):
        """Seconds since the last successful read, or None if there was none."""
        if not self.read_at:
            return None
        return max(0.0, (now if now is not None else time.time()) - self.read_at)

    def refresh(self):
        """Ask, in whatever thread this is called from."""
        started = time.time()
        try:
            data = self._read()
        except Exception as exc:  # noqa: BLE001 - the message is the result
            self.error = str(exc) or exc.__class__.__name__
            self.status = FAILED
        else:
            self.data = data
            self.error = ""
            self.read_at = time.time()
            self.status = OK
        self.took = time.time() - started
        self.reads += 1
        return self


def describe_age(seconds, never="noch nicht gelesen"):
    """How long ago, in words a window can print without doing arithmetic."""
    if seconds is None:
        return never
    if seconds < 45:
        return "gerade eben"
    minutes = int(seconds // 60)
    if minutes < 60:
        return f"vor {max(minutes, 1)} Minute{'n' if minutes != 1 else ''}"
    hours = int(seconds // 3600)
    if hours < 24:
        return f"vor {hours} Stunde{'n' if hours != 1 else ''}"
    days = int(seconds // 86400)
    return f"vor {days} Tag{'en' if days != 1 else ''}"


class Sources:
    """The shelf: every source, addressed by kind and name.

    Refreshing several at once is the point. Three AdGuards asked one after
    the other take three timeouts to fail; asked together they take one, and
    each says for itself how it went while the others are still running.
    """

    def __init__(self, workers=6):
        self.workers = workers
        self._sources = {}
        self._order = []
        # Reentrant on purpose: refresh() holds it while choosing what to ask,
        # and choosing reads the shelf through the same door.
        self._lock = threading.RLock()

    # -- what is on the shelf ----------------------------------------------

    def put(self, source):
        """Add a source, or keep the one that is there if it is the same one.

        Settings are edited while the window is open, and re-reading them must
        not throw away an answer that is still perfectly good. A source is the
        same one when its kind and name match -- what changed behind it is the
        callable, which is swapped in without touching the data.
        """
        key = (source.kind, source.name)
        with self._lock:
            existing = self._sources.get(key)
            if existing is None:
                self._sources[key] = source
                self._order.append(key)
                return source
            existing._read = source._read
            existing.label = source.label
            existing.settings = source.settings
            return existing

    def forget(self, kind, name):
        with self._lock:
            key = (kind, name)
            if key in self._sources:
                del self._sources[key]
                self._order.remove(key)

    def keep_only(self, kind, names):
        """Drop sources of this kind that are no longer configured."""
        wanted = set(names)
        for key in [k for k in list(self._order)
                    if k[0] == kind and k[1] not in wanted]:
            self.forget(*key)

    def get(self, kind, name):
        return self._sources.get((kind, name))

    def of_kind(self, kind):
        with self._lock:
            return [self._sources[key] for key in self._order if key[0] == kind]

    def all(self):
        with self._lock:
            return [self._sources[key] for key in self._order]

    def __len__(self):
        return len(self._sources)

    # -- asking ------------------------------------------------------------

    def pick(self, kinds=None, names=None):
        """The sources a refresh would touch, in the order they were added."""
        chosen = []
        for source in self.all():
            if kinds is not None and source.kind not in kinds:
                continue
            if names is not None and source.name not in names:
                continue
            chosen.append(source)
        return chosen

    def refresh(self, kinds=None, names=None, notify=None, block=False):
        """Ask the chosen sources, all at once.

        ``notify`` is called with each source as it turns to loading and again
        when it has answered -- from a worker thread, so a window has to hand
        it on to its own. Sources already being read are left alone: pressing
        refresh twice must not mean asking twice.

        Returns the sources this call took on, which is not necessarily the
        ones asked for.
        """
        say = notify or (lambda _source: None)
        with self._lock:
            taken = [s for s in self.pick(kinds, names) if s.status != LOADING]
            for source in taken:
                source.status = LOADING
        for source in taken:
            say(source)
        if not taken:
            return []

        def work(queue):
            while True:
                try:
                    source = queue.pop()
                except IndexError:
                    return
                source.refresh()
                say(source)

        queue = list(reversed(taken))
        threads = [threading.Thread(target=work, args=(queue,), daemon=True)
                   for _ in range(min(self.workers, len(taken)))]
        for thread in threads:
            thread.start()
        if block:
            for thread in threads:
                thread.join()
        return taken

    def busy(self, kinds=None):
        return [s for s in self.pick(kinds) if s.status == LOADING]

    def failed(self, kinds=None):
        return [s for s in self.pick(kinds) if s.status == FAILED]

    def summary(self, kinds=None):
        """One line's worth of "how is it going", for a tab header.

        Counted rather than described, so the caller picks the words: a tab
        that is loading says something different from the status tab.
        """
        chosen = self.pick(kinds)
        return {"total": len(chosen),
                "loading": sum(1 for s in chosen if s.status == LOADING),
                "ok": sum(1 for s in chosen if s.status == OK),
                "failed": sum(1 for s in chosen if s.status == FAILED),
                "idle": sum(1 for s in chosen if s.status == IDLE),
                "ready": sum(1 for s in chosen if s.ready)}

    def oldest(self, kinds=None, now=None):
        """The age of the stalest answer among them, or None if none has one."""
        ages = [s.age(now) for s in self.pick(kinds) if s.age(now) is not None]
        return max(ages) if ages else None
