"""Extract vanilla D2R layout/strings files from the game's CASC
storage into baselines/vanilla_<game-version>/ for the update doctor.

Uses CascLib.dll (bundled, sourced from D2RMM's tools) via casc.py.
Run once before a game update and once after, then run doctor.py.
"""
import os
import subprocess
import sys

import casc

HERE = os.path.dirname(os.path.abspath(__file__))
import config
GAME_EXE = config.GAME_EXE

WANT_PREFIXES = (
    "data:data/global/ui/layouts/",
    "data:data/local/lng/strings/",
    "data:data/hd/items/uniques.json",
)


def game_version():
    ps = "(Get-Item '{}').VersionInfo.FileVersion".format(GAME_EXE)
    out = subprocess.run(["powershell", "-NoProfile", "-Command", ps],
                         capture_output=True, text=True, timeout=30,
                         creationflags=getattr(subprocess,
                                               "CREATE_NO_WINDOW", 0))
    return (out.stdout.strip() or "unknown").replace(" ", "")


def main():
    if not casc.available():
        print("CascLib.dll or game install missing")
        return 1
    out_root = os.path.join(HERE, "baselines",
                            "vanilla_{}".format(game_version()))
    st = casc.Storage()
    n = 0
    try:
        for name, _size in st.find(b"*"):
            low = name.lower().replace("\\", "/")
            if not any(low.startswith(p) for p in WANT_PREFIXES):
                continue
            rel = low.split(":", 1)[-1]
            dest = os.path.join(out_root, rel.replace("/", os.sep))
            if st.extract(name.encode("utf-8"), dest):
                n += 1
    finally:
        st.close()
    print("extracted {} files -> {}".format(n, out_root))
    return 0


if __name__ == "__main__":
    sys.exit(main())
