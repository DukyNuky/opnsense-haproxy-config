"""Checks for reading a compose file before deploying -- see tests/run.py."""

import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import argparse

import portainer as pcore

ok = fail = 0
def check(label, got, want):
    global ok, fail
    if got == want: ok += 1
    else:
        fail += 1
        print(f"  FAIL {label}:\n    got  {got!r}\n    want {want!r}")


class Repo:
    """A repository as Portainer hands its files over, one path at a time."""

    def __init__(self, files):
        self.files = files
        self.asked = []

    def repo_file(self, repository, path, reference="", username="",
                  password="", skip_tls_verify=False):
        self.asked.append(path)
        if path not in self.files:
            raise pcore.PortainerError(f"{path} not found", status=404)
        return self.files[path]


def opts(compose_file="docker-compose.yml"):
    return argparse.Namespace(repository="https://git.example/x",
                              compose_file=compose_file, reference="main",
                              username="", password="", skip_tls_verify=False)


COMPOSE = """services:
  web:
    image: nginx
    env_file: .env
    ports:
      - "8080:80"
"""

print("-- the file a compose file points at is looked for ---------------")
repo = Repo({"docker-compose.yml": COMPOSE})
check("named and not there", pcore.required_env_files(repo, opts()), [".env"])
check("both files were asked for", repo.asked, ["docker-compose.yml", ".env"])

print("-- and nothing is reported when it is there ---------------------")
repo = Repo({"docker-compose.yml": COMPOSE, ".env": "A=1\n"})
check("there, so nothing to say", pcore.required_env_files(repo, opts()), [])

print("-- an empty file is still a file --------------------------------")
# compose does not mind an empty env file; only a missing one stops it
repo = Repo({"docker-compose.yml": COMPOSE, ".env": ""})
check("empty counts as present", pcore.required_env_files(repo, opts()), [])

print("-- a compose file in a subfolder reads relative to itself -------")
repo = Repo({"stacks/app/compose.yml": COMPOSE})
check("beside the compose file",
      pcore.required_env_files(repo, opts("stacks/app/compose.yml")),
      ["stacks/app/.env"])

print("-- a compose file that names no env file -----------------------")
repo = Repo({"docker-compose.yml": "services:\n  web:\n    image: nginx\n"})
check("nothing required", pcore.required_env_files(repo, opts()), [])
check("only the compose file was fetched", repo.asked, ["docker-compose.yml"])

print("-- several services naming the same file ------------------------")
two = """services:
  web:
    image: nginx
    env_file:
      - common.env
      - secrets.env
  worker:
    image: busybox
    env_file:
      - common.env
"""
repo = Repo({"docker-compose.yml": two, "common.env": "A=1\n"})
check("the missing one only", pcore.required_env_files(repo, opts()),
      ["secrets.env"])
check("and the shared one was read once", repo.asked.count("common.env"), 1)

print("-- a compose file that cannot be read at all --------------------")
# not knowing is not the same as knowing something is missing: the deploy
# that follows will say why, and inventing a warning here would be noise
repo = Repo({})
check("says nothing", pcore.required_env_files(repo, opts()), [])

print("-- a path that climbs out of the repository is left alone -------")
climb = "services:\n  web:\n    image: nginx\n    env_file: ../../etc/passwd\n"
repo = Repo({"docker-compose.yml": climb})
check("not followed", pcore.required_env_files(repo, opts()), [])
check("and not even asked for", repo.asked, ["docker-compose.yml"])

print("-- what the reader makes of the ways env_file is written --------")
check("one name", pcore.compose_env_files("    env_file: .env"), [".env"])
check("a list", pcore.compose_env_files(
    "    env_file:\n      - a.env\n      - b.env\n"), ["a.env", "b.env"])
check("the long form", pcore.compose_env_files(
    "    env_file:\n      - path: a.env\n        required: false\n"), ["a.env"])
check("quoted", pcore.compose_env_files('    env_file: ".env"'), [".env"])
check("none at all", pcore.compose_env_files("services:\n  web:\n"), [])

print("-- a file the compose file says may be absent is not reported ---")
# "required: false" is compose saying it can do without; warning about it
# would be noise in the log of a deploy that works
soft = """services:
  web:
    image: nginx
    env_file:
      - path: optional.env
        required: false
"""
repo = Repo({"docker-compose.yml": soft})
check("not missed", pcore.required_env_files(repo, opts()), [])
check("but still offered as a source of values",
      pcore.compose_env_files(soft), ["optional.env"])

both = """services:
  web:
    image: nginx
    env_file:
      - path: shared.env
        required: false
  worker:
    image: busybox
    env_file:
      - shared.env
"""
repo = Repo({"docker-compose.yml": both})
check("one service insisting is enough",
      pcore.required_env_files(repo, opts()), ["shared.env"])

print(f"\n{ok} ok, {fail} fail")
sys.exit(1 if fail else 0)
