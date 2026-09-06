"""Docker, whoever is managing it.

The program used to have a Portainer tab. It now has a Docker tab, and which
manager answers behind it is a detail of the settings -- with one exception,
which is deliberate: how a stack was made stays visible, because "this follows
a repository" and "this was already running" mean different things to anyone
about to change something.
"""

from .dockhand import Dockhand
from .engine import Engine
from .model import (COMPOSE, FOUND, GIT, UNKNOWN, Container, Inventory, Origin,
                    Place, Port, Stack, describe_origin)
from .portainer import Portainer

# What the settings may say a Docker host is managed by.
ENGINES = {engine.kind: engine for engine in (Portainer, Dockhand)}
KINDS = tuple(ENGINES)
TITLES = {engine.kind: engine.title for engine in ENGINES.values()}
# What a settings entry without a manager means. Every entry written before
# there was a choice is a Portainer, and saying so beats asking again.
DEFAULT_KIND = Portainer.kind


def engine_for(name, settings):
    """Build the right adapter for one configured Docker host."""
    kind = str((settings or {}).get("manager") or DEFAULT_KIND).lower()
    engine = ENGINES.get(kind)
    if engine is None:
        known = ", ".join(TITLES[k] for k in KINDS)
        raise LookupError(f"{name}: „{kind}“ ist keine bekannte "
                          f"Docker-Verwaltung (bekannt: {known})")
    return engine(name, settings)


__all__ = ["COMPOSE", "FOUND", "GIT", "UNKNOWN", "Container", "Dockhand",
           "DEFAULT_KIND", "ENGINES", "Engine", "Inventory", "KINDS", "Origin",
           "Place", "Port", "Portainer", "Stack", "TITLES", "describe_origin",
           "engine_for"]
