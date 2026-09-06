#!/usr/bin/env python3
"""Run every check in this folder and say how it went.

No framework: the project is standard library only, and a test that needs an
install before it can say yes or no is one more thing between a change and the
answer to "did I break it".
"""

import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))


def main():
    names = sorted(name for name in os.listdir(HERE)
                   if name.startswith("test_") and name.endswith(".py"))
    if not names:
        print("no checks here")
        return 0
    bad = []
    for name in names:
        print(f"\n=== {name} " + "=" * max(0, 60 - len(name)))
        result = subprocess.run([sys.executable, "-u", os.path.join(HERE, name)])
        if result.returncode:
            bad.append(name)
    print()
    if bad:
        print(f"failed: {', '.join(bad)}")
        return 1
    print(f"all {len(names)} files passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
