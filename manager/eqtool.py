"""eqtool - external control script for the eq mod.

Menu tool: feature toggles via .bk renames (game falls back to vanilla
for missing override files), game-update detection, and update doctor.

Live eq tree is sacred: all mutations are dry-run unless --apply, and
every rename is journaled to renames.log for undo.

Usage:
  python eqtool.py            interactive menu (dry-run renames)
  python eqtool.py --apply    interactive menu, renames actually happen
"""
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
import config
EQ_ROOT = config.EQ_ROOT
GAME_EXE = config.GAME_EXE
FEATURES = os.path.join(HERE, "features.json")
STATE = os.path.join(HERE, "eqtool_state.json")
JOURNAL = os.path.join(HERE, "renames.log")


def game_version():
    ps = ("(Get-Item '{}').VersionInfo.FileVersion".format(GAME_EXE))
    try:
        out = subprocess.run(
            ["powershell", "-NoProfile", "-Command", ps],
            capture_output=True, text=True, timeout=30,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        return out.stdout.strip() or "unknown"
    except Exception:
        return "unknown"


def load_state():
    try:
        with open(STATE, encoding="utf-8") as f:
            return json.load(f)
    except OSError:
        return {}


def save_state(st):
    with open(STATE, "w", encoding="utf-8") as f:
        json.dump(st, f, indent=1)


def rescan():
    subprocess.run([sys.executable, os.path.join(HERE, "scan_features.py")],
                   capture_output=True, text=True,
                   creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    with open(FEATURES, encoding="utf-8") as f:
        return json.load(f)


def journal(line):
    with open(JOURNAL, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def set_feature(data, feat, enable, apply):
    rows = data["features"][feat]
    if any(r["toggle"] == "never" for r in rows):
        print("  refusing: feature contains protected files")
        return
    n = 0
    for r in rows:
        full = os.path.join(EQ_ROOT, r["path"].replace("/", os.sep))
        if enable and r["disabled"]:
            src, dst = full, full[:-3]  # strip .bk
        elif not enable and not r["disabled"]:
            src, dst = full, full + ".bk"
        else:
            continue
        n += 1
        if apply:
            os.rename(src, dst)
            journal("{} -> {}".format(src, dst))
        else:
            print("  DRY-RUN rename: {} -> {}".format(src, dst))
    verb = "enabled" if enable else "disabled"
    print("  {} {} ({} files{})".format(
        verb, feat, n, "" if apply else ", dry-run"))


def feature_state(rows):
    off = sum(r["disabled"] for r in rows)
    if off == 0:
        return "ON"
    if off == len(rows):
        return "OFF"
    return "MIXED({}/{})".format(len(rows) - off, len(rows))


def doctor():
    print("\n[update doctor]")
    r = subprocess.run([sys.executable, os.path.join(HERE, "doctor.py")],
                       text=True)
    return r.returncode


def menu(apply):
    data = rescan()
    st = load_state()
    ver = game_version()
    if st.get("game_version") and st["game_version"] != ver:
        print("!! D2R updated: {} -> {}".format(st["game_version"], ver))
        print("!! Run the update doctor (option d) to re-baseline and merge.")
    st["game_version"] = ver
    save_state(st)

    while True:
        feats = sorted(data["features"])
        print("\n=== eqtool ===  game {}  {}".format(
            ver, "(APPLY MODE)" if apply else "(dry-run; use --apply)"))
        for i, feat in enumerate(feats, 1):
            rows = data["features"][feat]
            sz = sum(r["size"] for r in rows) / 1e6
            print(" {:2d}. [{:>4s}] {:20s} {:4d} files {:7.1f} MB  {}".format(
                i, feature_state(rows), feat, len(rows), sz,
                "(shared-file: all-or-nothing)"
                if any(r["toggle"] == "shared" for r in rows) else ""))
        print("  d. d2r updated - run update doctor")
        print("  r. rescan    q. quit")
        choice = input("> ").strip().lower()
        if choice == "q":
            return 0
        if choice == "r":
            data = rescan()
            continue
        if choice == "d":
            doctor()
            continue
        if choice.isdigit() and 1 <= int(choice) <= len(feats):
            feat = feats[int(choice) - 1]
            cur = feature_state(data["features"][feat])
            set_feature(data, feat, enable=(cur != "ON"), apply=apply)
            data = rescan()
        else:
            print("  ?")


if __name__ == "__main__":
    sys.exit(menu(apply="--apply" in sys.argv))
