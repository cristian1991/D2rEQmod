"""Feature scanner for the eq mod (read-only).

Walks the live eq tree, buckets every file into a named feature using
path rules first, then source-map module attribution as fallback.
Outputs features.json (machine) and a console report (human).

Toggle method per file:
  rename  - standalone override; renaming to .bk makes the game fall
            back to vanilla for that file. Safe per-file toggle.
  shared  - file carries multiple features merged together (strings,
            shared layouts, profiles). Rename disables ALL of them;
            flagged so the toggler treats the whole file as one switch
            or leaves it always-on.
"""
import json
import os
import re
import sys
from collections import defaultdict

import config
EQ_ROOT = config.EQ_ROOT
SOURCE_MAP = (
    r"D:\Games\D2rp\.MEMORY\sessions"
    r"\2026-07-02-mod-merge-system-for-eq-conflict-aware-composite-b"
    r"\artifacts\eq-source-map.json"
)
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "features.json")

# Ordered path rules: first match wins. (feature, toggle, regex on
# forward-slash relative path lowercased)
RULES = [
    ("core-modinfo",        "never",  r"^modinfo\.json$"),
    ("core-modinfo",        "never",  r"^data/global/dataversionbuild\.txt$"),
    ("npc-glow",            "rename", r"^data/hd/nickname/"),
    ("npc-glow",            "rename", r"^data/hd/character/npc/"),
    ("floor-effects",       "rename", r"^data/hd/items/misc/(rune|gem|key|charm|quest|body_part)/"),
    ("intro-videos",        "rename", r"^data/hd/global/video/.*\.webm$"),
    ("waypoint-lights",     "rename", r"^data/hd/objects/waypoint_portals/"),
    ("waypoint-lights",     "rename", r"^data/hd/global/tiles/.*automap"),
    ("show-item-level",     "rename", r"^data/global/excel/(armor|weapons|misc)\.txt$"),
    ("golden-cursor",       "rename", r"^data/hd/global/ui/cursor/"),
    ("trav-wall-remove",         "rename", r"^data/global/tiles/.*travn\.json$"),
    ("trav-wall-remove",         "rename", r"travn\.json$"),
    ("coa-crown",        "rename", r"^data/hd/items/armor/helmet/crown_winged\.json$"),
    ("coa-crown",        "rename", r"^data/hd/items/uniques\.json$"),
    ("coa-crown",        "rename", r"^data/hd/items/armor/circlet/eq_coa"),
    ("coa-crown",        "rename", r"^data/hd/items/armor/circlet/diadem/armor_eqcoa1_alb\.texture$"),
    ("coa-crown",        "rename", r"^data/hd/items/armor/helmet/crown/textures/crown_eqfl_alb\.texture$"),
    ("coa-crown",        "rename", r"^data/hd/texture_desc_cache\.json$"),
    ("coa-crown",        "rename", r"^data/hd/global/ui/items/armor/circlet/eq_coa.*.sprite$"),
    ("better-runes",        "rename", r"^data/hd/items/"),          # remaining item sprites
    ("hud-monster-health",  "rename", r"hudmonsterhealthhd\.json$"),
    ("pro-bars",            "rename", r"(hpprobar|healthprobar|manaprobar)hd\.json$"),
    ("main-menu-layout",    "rename", r"(mainmenupanel|mainmenubuttonribbon|characterdifficultymodal)hd\.json$"),
    ("npc-dialog-style",    "rename", r"npcdialogpanelhd\.json$"),
    ("ui-profiles",         "shared", r"^data/global/ui/layouts/(controller/)?_profile(hd|lv|sd)\.json$"),
    ("hud-panel",           "shared", r"^data/global/ui/layouts/(controller/)?hudpanelhd\.json$"),
    ("inventory-panels",    "shared", r"^data/global/ui/layouts/(controller/)?playerinventory.*\.json$"),
    ("ui-layouts-misc",     "shared", r"^data/global/ui/layouts/"),
    ("strings",             "shared", r"^data/local/lng/strings/"),
    ("ui-sprites",          "rename", r"^data/hd/global/ui/panel/"),
    ("ui-sprites",          "rename", r"^data/hd/global/ui/"),
    ("fonts",               "rename", r"^data/hd/ui/fonts/"),
]

# For generic buckets, source-map module attribution refines the feature.
GENERIC = {"ui-sprites", "better-runes", "floor-effects"}
MODULE_FEATURE = {
    "waypoint_lights": "waypoint-lights",
    "better_runes": "better-runes",
    "golden_mouse": "golden-cursor",
    "wall_remove": "trav-wall-remove",
    "lightpillar": "light-pillars",
}

def load_source_map():
    try:
        with open(SOURCE_MAP, encoding="utf-8") as f:
            raw = json.load(f)
    except OSError:
        return {}
    out = {}
    for k, v in raw.items():
        rel = k.split("eq.mpq/", 1)[-1].lower()
        cands = v.get("candidates") or []
        out[rel] = cands[0]["module"] if cands else None
    return out

def main():
    smap = load_source_map()
    features = defaultdict(list)
    unmatched = []
    for root, _, files in os.walk(EQ_ROOT):
        for fn in files:
            full = os.path.join(root, fn)
            rel = os.path.relpath(full, EQ_ROOT).replace("\\", "/")
            rl = rel.lower()
            if rl.endswith(".bk"):
                rl_active = rl[:-3]
            else:
                rl_active = rl
            for feat, toggle, pat in RULES:
                if re.search(pat, rl_active):
                    mod = smap.get(rl_active)
                    if feat in GENERIC and mod in MODULE_FEATURE:
                        feat = MODULE_FEATURE[mod]
                    features[feat].append({
                        "path": rel,
                        "toggle": toggle,
                        "disabled": rl.endswith(".bk"),
                        "module": smap.get(rl_active),
                        "size": os.path.getsize(full),
                    })
                    break
            else:
                unmatched.append({"path": rel, "module": smap.get(rl_active),
                                  "size": os.path.getsize(full)})

    result = {"eq_root": EQ_ROOT, "features": dict(features),
              "unmatched": unmatched}
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=1)

    total = sum(len(v) for v in features.values()) + len(unmatched)
    print(f"scanned {total} files -> {len(features)} features "
          f"({len(unmatched)} unmatched)\n")
    for feat in sorted(features):
        rows = features[feat]
        sz = sum(r["size"] for r in rows) / 1e6
        tog = {r["toggle"] for r in rows}
        off = sum(r["disabled"] for r in rows)
        mods = {r["module"] for r in rows if r["module"]}
        print(f"{feat:20s} {len(rows):4d} files {sz:8.1f} MB  "
              f"toggle={'/'.join(sorted(tog)):6s} "
              f"{'DISABLED:'+str(off) if off else '':12s} "
              f"src={','.join(sorted(mods)) or '-'}")
    if unmatched:
        print("\nunmatched:")
        for u in unmatched:
            print(f"  {u['path']}  src={u['module'] or '-'}")

if __name__ == "__main__":
    sys.exit(main())
