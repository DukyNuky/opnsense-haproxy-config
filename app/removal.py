"""Taking one entry out of every system it was put into.

Making an entry touches three places and leaving it takes the same three:
the rule and the pool and the server on the firewall, the name in every
AdGuard that answers for it, and nothing at all in Docker -- the container is
the service itself, and a proxy entry going away is no reason for it to stop
running. Saying that out loud is part of the job here: a window that offers
to remove something "everywhere" has to be exact about where everywhere ends.

The firewall side is not rewritten. ``deprovision`` has been doing it since
1.0, it knows what may go and what is still used by something else, and it
can be asked first without changing anything -- which is what the plan below
is. The one thing added is DNS across several servers: the firewall's own
removal knows one AdGuard, and the whole point of the status page is that it
reads all of them.

Nothing here draws anything, so all of it can be checked without a display.
"""

import argparse

import opnsense_haproxy as core

from . import wiring


def operation_for(chain):
    """Which of the two removals this chain needs."""
    return (core.deprovision_listener if chain.kind == "listener"
            else core.deprovision)


def options_for(chain, dry_run=True, no_apply=False):
    """The arguments the removal expects, out of what the chain knows.

    ``yes`` is set because the confirming already happened in front of a
    person who could read what was going to go; asking again on a terminal
    nobody is watching would hang the worker thread for good.
    """
    data = chain.data or {}
    if chain.kind == "listener":
        return argparse.Namespace(name=data.get("service", ""),
                                  host=data.get("host", ""),
                                  dry_run=dry_run, no_apply=no_apply, yes=True)
    return argparse.Namespace(
        target=data.get("target") or f"{chain.name}{chain.path}",
        base_domain="", prefix=data.get("prefix", ""),
        dry_run=dry_run, no_apply=no_apply, yes=True)


def firewall_of(shelf, chain):
    """The source the chain was read from, which is the one to write to."""
    return shelf.get(wiring.OPNSENSE, chain.where)


def dns_holders(sources, host):
    """Every AdGuard that answers for this name, with the answer it gives.

    Asking only the AdGuard written next to the firewall would take the name
    off that one and leave it standing on the others -- and a name that is
    gone in one place and not in another is worse than one that is still
    there, because nobody can see which server they got.

    A server that was not read is not in here. It cannot be: an entry cannot
    be removed from a list nobody has.
    """
    wanted = str(host or "").strip().lower()
    if not wanted:
        return []
    found = []
    for source in sources:
        for entry in (source.data or []):
            if not isinstance(entry, dict):
                continue
            if str(entry.get("domain", "")).strip().lower() == wanted:
                found.append((source, str(entry.get("answer", "")).strip()))
    return found


def unread_dns(sources):
    """The AdGuards nobody could look in, by name.

    They are the reason a removal can be honest and still incomplete: the
    name may stand on one of them, and this program has no way to know.
    """
    return [source.name for source in sources if not source.ready]


def dns_plan(sources, host):
    """What removing the name from DNS would do, in lines to read."""
    lines = [f"DNS-Eintrag {host} → {answer or '?'} auf {source.name}"
             for source, answer in dns_holders(sources, host)]
    return lines


def remove_dns(sources, host, report=None):
    """Take the name out of every AdGuard that has it.

    Every server is tried even after one of them fails: half a removal
    because the first server was unreachable is the state this whole module
    exists to avoid.
    """
    say = report or (lambda _text: None)
    done, failed = [], []
    for source, answer in dns_holders(sources, host):
        try:
            wiring.dns_client(source.settings).delete_rewrite(host, answer)
        except Exception as exc:  # noqa: BLE001 - the message is the result
            failed.append((source.name, str(exc) or exc.__class__.__name__))
            say(f"! {source.name}: {exc}")
        else:
            done.append(source.name)
            say(f"- DNS-Eintrag {host} auf {source.name} entfernt")
    return done, failed


# What the removal prints, in the words the dialog uses. The report is
# written for a terminal and in English; a window that asks somebody to
# confirm a deletion has to say what goes in the language of the rest of it.
WORDS = (("public service", "Öffentlicher Dienst"),
         ("backend pool", "Backend-Pool"),
         ("real server", "Real Server"),
         ("dns rewrite", "DNS-Eintrag"),
         ("condition", "Bedingung"),
         ("rule", "Regel"))


def german(line):
    """One line of the report, said in German -- or left exactly as it is.

    Anything unrecognised is passed through untouched. A line nobody planned
    for is still worth reading, and guessing at it would be worse than the
    English.
    """
    text = " ".join(str(line).split())
    if text.startswith("will delete "):
        rest = text[len("will delete "):]
        for english, word in WORDS:
            if rest.startswith(english):
                return f"{word} {rest[len(english):].strip()}"
        return rest
    if text.startswith("- deleted "):
        rest = text[len("- deleted "):]
        for english, word in WORDS:
            if rest.startswith(english):
                return f"{word} {rest[len(english):].strip()} entfernt"
        return f"{rest} entfernt"
    for english, word in WORDS:
        if text.startswith(english + " :") or text.startswith(english + ":"):
            return f"{word}: {text.split(':', 1)[1].strip()}"
    if text.startswith("keeping"):
        return f"bleibt stehen: {text.split(':', 1)[1].strip()}"
    if text.startswith("nothing found for "):
        return ("Auf der OPNsense ist dazu nichts (mehr) zu finden: "
                + text[len("nothing found for "):])
    return text


def plan_lines(log):
    """The trial run's report, as the lines a person is asked to confirm."""
    lines = []
    for entry in log or []:
        text = " ".join(str((entry or {}).get("text", "")).split())
        if not text or text.startswith("dry run"):
            continue
        lines.append(german(text))
    return lines


# What is deliberately left alone, and why. Shown with the plan, because
# "everywhere" is a promise and these are its edges.
KEPT = [
    ("Der Container läuft weiter", "Er ist der Dienst selbst — dass er nicht "
     "mehr über den Proxy erreichbar ist, heißt nicht, dass er weg soll."),
    ("Das Zertifikat bleibt", "Es gilt meist für mehrere Namen und wird von "
     "ACME verwaltet, nicht von hier."),
]
