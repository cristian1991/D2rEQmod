"""Layout-node patch toggles for shared UI layout files.

Same idea as patches.py (string key groups) but the unit of ownership
is a top-level layout node: either an entry of the root "children"
array (identified by its "name") or a root-level variable key in the
_profile* files. Toggling swaps the whole owned subtree between the
custom version (snapshot) and the vanilla baseline (or removes nodes
we invented). Nothing else in the file is touched.

Note: writing goes through json.dump, so comments in the live files
are lost on first toggle — functionally irrelevant to the game.
"""
import json
import os

from doctor import jload  # lenient JSONC loader

HERE = os.path.dirname(os.path.abspath(__file__))
import config
EQ_LAYOUTS = os.path.join(config.EQ_ROOT, "data", "global", "ui", "layouts")
SNAPSHOT = os.path.join(HERE, "patches", "custom_layouts.json")

HUD = "hudpanelhd.json"
INV = ["playerinventoryoriginallayouthd.json",
       "playerinventoryexpansionlayouthd.json",
       "controller/playerinventoryoriginallayouthd.json",
       "controller/playerinventoryexpansionlayouthd.json"]
PROFILES = ["_profilehd.json", "_profilelv.json", "_profilesd.json"]

COMPACT_KEYS = ["LeftPanelRect", "RightPanelRect", "LeftSideSprite",
                "RightSideSprite", "LeftHingeSprite", "RightHingeSprite"]
NPC_KEYS = ["NPCSpointFontSize", "StyleNPCDialogueSize"]

MHP = "hudmonsterhealthhd.json"
MHP_C = "controller/hudmonsterhealthhd.json"

# group -> {file: {"children": [...names or "auto"], "rootkeys": [...]}}
GROUPS = {
    "orbs-hud": {HUD: {"children": ["HealthBall", "ManaBall"]}},
    # the operator's hand-built top monster bar: every changed node
    # EXCEPT TargetAttached, which belongs to overhead-bars below.
    # Both live in the same file and toggle independently.
    "monster-topbar": {MHP: {"children": "auto"},
                       MHP_C: {"children": "auto"}},
    "overhead-bars": {MHP: {"children": ["TargetAttached"]}},
    "hud-tweaks": {HUD: {"children": "auto"}},   # every other changed child
    "cube-convert": {f: {"children": ["convert"]} for f in INV},
    "info-buttons": {f: {"children": "auto"} for f in INV},
    "compact-windows": {f: {"rootkeys": COMPACT_KEYS} for f in PROFILES},
    "npc-vars": {"_profilehd.json": {"rootkeys": NPC_KEYS}},
}
# groups that claim children explicitly, per file (for "auto" exclusion)
_EXPLICIT = {}
for g, files in GROUPS.items():
    for fn, spec in files.items():
        kids = spec.get("children")
        if isinstance(kids, list):
            _EXPLICIT.setdefault(fn, set()).update(kids)


def _baseline(fn):
    root = os.path.join(HERE, "baselines")
    vs = sorted(d for d in os.listdir(root) if d.startswith("vanilla_"))
    p = os.path.join(root, vs[-1], "data", "global", "ui", "layouts",
                     fn.replace("/", os.sep))
    return jload(p) if os.path.isfile(p) else None


def _live_path(fn):
    return os.path.join(EQ_LAYOUTS, fn.replace("/", os.sep))


def _kids(doc):
    return {c.get("name"): c for c in doc.get("children", [])
            if isinstance(c, dict)}


def snapshot():
    snap = {}
    for g, files in GROUPS.items():
        snap[g] = {}
        for fn, spec in files.items():
            lp = _live_path(fn)
            if not os.path.isfile(lp):
                continue
            live = jload(lp)
            base = _baseline(fn)
            entry = {}
            kids = spec.get("children")
            if kids:
                lk = _kids(live)
                bk = _kids(base) if base else {}
                if kids == "auto":
                    kids = [n for n, c in lk.items()
                            if n not in _EXPLICIT.get(fn, set())
                            and (n not in bk or bk[n] != c)]
                entry["children"] = {n: lk[n] for n in kids if n in lk}
            for k in spec.get("rootkeys", []):
                if k in live:
                    entry.setdefault("rootkeys", {})[k] = live[k]
            if entry.get("children") or entry.get("rootkeys"):
                snap[g][fn] = entry
    # preserve previously seeded custom nodes that are not currently in
    # the live tree (e.g. transplants toggled OFF at snapshot time)
    if os.path.isfile(SNAPSHOT):
        old = json.load(open(SNAPSHOT, encoding="utf-8"))
        for g, files in old.items():
            for fn, entry in files.items():
                tgt = snap.setdefault(g, {}).setdefault(fn, {})
                for n, sub in entry.get("children", {}).items():
                    tgt.setdefault("children", {}).setdefault(n, sub)
                for k, v in entry.get("rootkeys", {}).items():
                    tgt.setdefault("rootkeys", {}).setdefault(k, v)
    os.makedirs(os.path.dirname(SNAPSHOT), exist_ok=True)
    with open(SNAPSHOT, "w", encoding="utf-8") as f:
        json.dump(snap, f, ensure_ascii=False, indent=1)
    return {g: {fn: {k: len(v) for k, v in e.items()}
                for fn, e in files.items()}
            for g, files in snap.items()}


def _snap():
    return json.load(open(SNAPSHOT, encoding="utf-8"))


def state(group):
    snap = _snap().get(group, {})
    on = off = 0
    for fn, entry in snap.items():
        lp = _live_path(fn)
        if not os.path.isfile(lp):
            continue
        live = jload(lp)
        lk = _kids(live)
        for n, custom in entry.get("children", {}).items():
            if n in lk and lk[n] == custom:
                on += 1
            else:
                off += 1
        for k, custom in entry.get("rootkeys", {}).items():
            if live.get(k) == custom:
                on += 1
            else:
                off += 1
    if on and off:
        return "MIXED"
    return "ON" if on else "OFF"


def files_info(group):
    snap = _snap().get(group, {})
    out = []
    for fn, entry in snap.items():
        n = len(entry.get("children", {})) + len(entry.get("rootkeys", {}))
        out.append({"path": "data/global/ui/layouts/" + fn +
                    "  ({} nodes)".format(n),
                    "bk": state(group) == "OFF"})
    return out


def set_group(group, enable):
    snap = _snap().get(group, {})
    changed = 0
    for fn, entry in snap.items():
        lp = _live_path(fn)
        if not os.path.isfile(lp):
            continue
        live = jload(lp)
        base = _baseline(fn)
        bk = _kids(base) if base else {}
        children = live.setdefault("children", [])
        idx = {c.get("name"): i for i, c in enumerate(children)
               if isinstance(c, dict)}
        for n, custom in entry.get("children", {}).items():
            if enable:
                if n in idx:
                    if children[idx[n]] != custom:
                        children[idx[n]] = custom
                        changed += 1
                else:
                    children.append(custom)
                    changed += 1
            else:
                if n in bk:
                    if n in idx and children[idx[n]] != bk[n]:
                        children[idx[n]] = bk[n]
                        changed += 1
                elif n in idx:
                    children[idx[n]] = None
                    changed += 1
        live["children"] = [c for c in children if c is not None]
        for k, custom in entry.get("rootkeys", {}).items():
            if enable:
                if live.get(k) != custom:
                    live[k] = custom
                    changed += 1
            else:
                if base and k in base:
                    if live.get(k) != base[k]:
                        live[k] = base[k]
                        changed += 1
                elif k in live:
                    del live[k]
                    changed += 1
        with open(lp, "w", encoding="utf-8") as f:
            json.dump(live, f, ensure_ascii=False, indent=2)
    return changed


if __name__ == "__main__":
    print(json.dumps(snapshot(), indent=1))
