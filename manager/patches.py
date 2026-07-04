"""Key-group patch toggles for shared string files.

Rename-toggles can't split features that share one JSON file, so these
options work at key level: each group owns a set of string keys, and
toggling rewrites only those entries — custom value when ON, vanilla
baseline value (or removal, for keys we invented) when OFF. Everything
else in the file is byte-for-byte untouched.

The custom values live in patches/custom_strings.json, snapshotted
from the live eq tree (run snapshot() after editing strings by hand).
npcs.json stays the container for all custom keys by design — it is
the smallest, least-patched string file (operator decision).
"""
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
import config
EQ_STRINGS = os.path.join(config.EQ_ROOT, "data", "local", "lng", "strings")
SNAPSHOT = os.path.join(HERE, "patches", "custom_strings.json")

# Keys we invented (absent from vanilla): OFF removes them entirely.
PANEL_TEXT_KEYS = (
    ["hudpanelStr%d" % i for i in range(3, 13)]
    + ["minihealthOn", "panelhealth", "panelmana"]
)

# group -> {file: "auto-changed"} means: every key in that file that
# differs from baseline and is not claimed by another group.
GROUPS = {
    "panel-texts": {
        "desc": "Custom item-info and HUD panel texts.",
        "files": {"npcs.json": PANEL_TEXT_KEYS},
    },
    "npc-names": {
        "desc": "Styled NPC names and titles (yupgoolg).",
        "files": {"npcs.json": "auto-changed"},
    },
    "item-icons-and-nameplates": {
        "desc": "Item name icons and shorthand for runes, gems and bases.",
        "files": {
            "item-names.json": "auto-changed",
            "item-runes.json": "auto-changed",
            "item-nameaffixes.json": "auto-changed",
            "item-modifiers.json": "auto-changed",
        },
    },
}


def _baseline_dir():
    root = os.path.join(HERE, "baselines")
    vs = sorted(d for d in os.listdir(root) if d.startswith("vanilla_"))
    return os.path.join(root, vs[-1], "data", "local", "lng", "strings")


def _load(path):
    with open(path, encoding="utf-8-sig") as f:
        return json.load(f)


def _entries(path):
    return {e["Key"]: e for e in _load(path) if "Key" in e}


def _norm(entry):
    """Ownership/compare scope: the enUS text only. Locale drift from
    old string dumps is not part of any mod option."""
    return entry.get("enUS")


def snapshot():
    """Capture current live values of every group key (assumes the live
    tree currently has all customizations applied)."""
    base_dir = _baseline_dir()
    snap = {}
    claimed = {}  # file -> set(keys claimed by explicit lists)
    for g, spec in GROUPS.items():
        for fn, keys in spec["files"].items():
            if isinstance(keys, list):
                claimed.setdefault(fn, set()).update(keys)
    for g, spec in GROUPS.items():
        snap[g] = {}
        for fn, keys in spec["files"].items():
            live = _entries(os.path.join(EQ_STRINGS, fn))
            bp = os.path.join(base_dir, fn)
            base = _entries(bp) if os.path.isfile(bp) else {}
            if keys == "auto-changed":
                keys = [k for k, e in live.items()
                        if k not in claimed.get(fn, set())
                        and (k not in base or _norm(base[k]) != _norm(e))]
            snap[g][fn] = {k: live[k] for k in keys if k in live}
    os.makedirs(os.path.dirname(SNAPSHOT), exist_ok=True)
    with open(SNAPSHOT, "w", encoding="utf-8") as f:
        json.dump(snap, f, ensure_ascii=False, indent=1)
    return {g: sum(len(v) for v in files.values())
            for g, files in snap.items()}


def _snap():
    return _load(SNAPSHOT)


def state(group):
    """ON if the group's keys currently carry the custom values."""
    snap = _snap()[group]
    base_dir = _baseline_dir()
    on = off = 0
    for fn, entries in snap.items():
        live = _entries(os.path.join(EQ_STRINGS, fn))
        for k, custom in entries.items():
            if k in live and _norm(live[k]) == _norm(custom):
                on += 1
            else:
                off += 1
    if on and off:
        return "MIXED"
    return "ON" if on else "OFF"


def files_info(group):
    snap = _snap()[group]
    return [{"path": "data/local/lng/strings/" + fn +
             "  ({} keys)".format(len(entries)),
             "bk": state(group) == "OFF"}
            for fn, entries in snap.items()]


def set_group(group, enable):
    snap = _snap()[group]
    base_dir = _baseline_dir()
    changed = 0
    for fn, entries in snap.items():
        path = os.path.join(EQ_STRINGS, fn)
        data = _load(path)
        by_key = {e.get("Key"): i for i, e in enumerate(data)}
        bp = os.path.join(base_dir, fn)
        base = _entries(bp) if os.path.isfile(bp) else {}
        max_id = max((e.get("id", 0) for e in data), default=0)
        for k, custom in entries.items():
            if enable:
                if k in by_key:
                    if _norm(data[by_key[k]]) != _norm(custom):
                        data[by_key[k]]["enUS"] = custom.get("enUS")
                        changed += 1
                else:
                    entry = dict(custom)
                    if "id" in entry:
                        max_id += 1
                        entry["id"] = max_id
                    data.append(entry)
                    changed += 1
            else:
                if k in base:
                    if k in by_key and _norm(data[by_key[k]]) != _norm(base[k]):
                        data[by_key[k]]["enUS"] = base[k].get("enUS")
                        changed += 1
                elif k in by_key:
                    data[by_key[k]] = None
                    changed += 1
        data = [e for e in data if e is not None]
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    return changed


if __name__ == "__main__":
    print(snapshot())
