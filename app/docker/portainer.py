"""Portainer, said in the words of app.docker.model.

The client underneath is the one that has been doing this work since 1.4 --
portainer.py, with its retries, its timeouts and everything it learned about
Portainer answering differently from one version to the next. None of that is
rewritten here. What this file does is translate: Portainer's numbers and
capitals in, one vocabulary out.
"""

import portainer as api

from .engine import Engine, build_inventory, build_stack, read_container
from .model import COMPOSE, FOUND, GIT, Origin, Place


def read_origin(stack):
    """How Portainer says this stack was made.

    Portainer has no field for it. A GitConfig means it was cloned and follows
    the repository; anything else was handed a compose file. "Found running"
    it does not know at all -- an external stack is one it did not create, and
    that shows up as a stack with no compose of its own.
    """
    git = api.git_config(stack)
    if git:
        auto = api.auto_update_of(stack) or {}
        return Origin(kind=GIT,
                      repository=str(git.get("URL", "")),
                      reference=str(git.get("ReferenceName", "")),
                      compose_file=str(git.get("ConfigFilePath", "")),
                      authenticated=bool(git.get("Authentication")),
                      auto_update=(auto.get("interval")
                                   or ("webhook" if auto.get("webhook") else "")))
    # Type 0 is what Portainer reports for a stack it merely noticed
    if not stack.get("Id") or int(stack.get("Type") or 0) == 0:
        return Origin(kind=FOUND)
    return Origin(kind=COMPOSE)


class Portainer(Engine):
    kind = "portainer"
    title = "Portainer"

    def __init__(self, name, settings):
        super().__init__(name, settings)
        self.client = api.Portainer(
            self.url,
            api_key=self.settings.get("api_key", ""),
            username=self.settings.get("username", ""),
            password=self.settings.get("password", ""),
            verify=self.settings.get("verify_ssl", True) is not False)

    def check(self):
        return {"manager": self.title, "version": self.client.version()}

    def places(self):
        return [Place(id=str(entry.get("Id")),
                      name=str(entry.get("Name", "")),
                      url=str(entry.get("URL", "")),
                      # 1 is up in Portainer's book; anything else is not
                      reachable=int(entry.get("Status") or 0) == 1)
                for entry in self.client.endpoints()]

    def read(self, place=None):
        places = self.places()
        chosen = self.pick_place(places, place)
        containers = [read_container(entry)
                      for entry in self.client.containers(chosen.id)]
        stacks = []
        for raw in self.client.stacks():
            if str(raw.get("EndpointId")) != str(chosen.id):
                continue
            stacks.append(build_stack(
                name=str(raw.get("Name", "")),
                containers=containers,
                ref=str(raw.get("Id")),
                place=chosen.id,
                origin=read_origin(raw),
                env=[f"{v.get('name')}={v.get('value')}"
                     if isinstance(v, dict) else str(v)
                     for v in (raw.get("Env") or [])]))
        return build_inventory(chosen, places, stacks, containers)
