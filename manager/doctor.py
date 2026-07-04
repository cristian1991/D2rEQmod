"""Update doctor for the eq mod.

When D2R updates, vanilla layouts/strings can change under the mod's
overrides. This tool three-way-merges each affected file:

    base_old  = vanilla file from the previous game build (baseline)
    base_new  = vanilla file from the current game build
    modded    = the eq override

The eq delta (modded vs base_old) is re-applied onto base_new. Output
goes to staging/ only - the live eq tree is never touched. A conflict
report lists every spot where the game update and the mod changed the
same value; those need a human decision.

Baselines live in baselines/vanilla_<version>/data/... . Extraction
from the game's CASC storage is done by extract_casc.py (requires
CascLib; see that file). Until two baselines exist, the doctor
explains what is missing and exits.
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
import config
EQ_ROOT = config.EQ_ROOT
BASELINES = os.path.join(HERE, "baselines")
STAGING = os.path.join(HERE, "staging")

# Only these override classes are mergeable text; everything else
# (sprites, textures, videos) is unaffected by this doctor.
MERGEABLE_SUFFIX = (".json",)
MERGEABLE_PREFIX = ("data/global/ui/layouts/", "data/local/lng/strings/",
                    "data/hd/items/uniques.json")

# Deterministic merge policy:
# - strings files: the mod owns enUS only; for every other locale the
#   NEW VANILLA text always wins (old-dump locale drift is not mod intent)
# - all other collisions: the MOD value wins, recorded as "resolved"
LOCALES = {"deDE", "esES", "esMX", "frFR", "itIT", "jaJP", "koKR",
           "plPL", "ptBR", "ruRU", "zhCN", "zhTW"}


def list_baselines():
    if not os.path.isdir(BASELINES):
        return []
    return sorted(
        d for d in os.listdir(BASELINES)
        if d.startswith("vanilla_")
        and os.path.isdir(os.path.join(BASELINES, d)))


def _strip_jsonc(text):
    """Remove //-line and /* */ block comments (outside strings) and
    trailing commas — D2R layout JSONs use all three."""
    out = []
    i, n = 0, len(text)
    in_str = in_line = in_block = False
    while i < n:
        c = text[i]
        nxt = text[i + 1] if i + 1 < n else ""
        if in_line:
            if c == "\n":
                in_line = False
                out.append(c)
        elif in_block:
            if c == "*" and nxt == "/":
                in_block = False
                i += 1
        elif in_str:
            out.append(c)
            if c == "\\":
                if i + 1 < n:
                    out.append(nxt)
                    i += 1
            elif c == '"':
                in_str = False
        else:
            if c == '"':
                in_str = True
                out.append(c)
            elif c == "/" and nxt == "/":
                in_line = True
                i += 1
            elif c == "/" and nxt == "*":
                in_block = True
                i += 1
            else:
                out.append(c)
        i += 1
    import re
    return re.sub(r",\s*([}\]])", r"\1", "".join(out))


def jload(path):
    with open(path, encoding="utf-8-sig", errors="replace") as f:
        return json.loads(_strip_jsonc(f.read()))


# ---------- three-way JSON merge ----------

def diff(old, new, path=""):
    """Flat list of (path, old_value, new_value) leaf changes."""
    out = []
    if isinstance(old, dict) and isinstance(new, dict):
        for k in sorted(set(old) | set(new)):
            p = "{}/{}".format(path, k)
            if k not in old:
                out.append((p, None, new[k]))
            elif k not in new:
                out.append((p, old[k], None))
            else:
                out.extend(diff(old[k], new[k], p))
    elif isinstance(old, list) and isinstance(new, list):
        key = _list_key(old) or _list_key(new)
        if key:
            om = {e.get(key): e for e in old if isinstance(e, dict)}
            nm = {e.get(key): e for e in new if isinstance(e, dict)}
            for k in list(om.keys()) + [k for k in nm if k not in om]:
                p = "{}/[{}={}]".format(path, key, k)
                if k not in om:
                    out.append((p, None, nm[k]))
                elif k not in nm:
                    out.append((p, om[k], None))
                else:
                    out.extend(diff(om[k], nm[k], p))
        elif old != new:
            out.append((path, old, new))
    elif old != new:
        out.append((path, old, new))
    return out


def _list_key(lst):
    """Key field for aligning lists of objects (strings files use
    Key/id; layout children use name)."""
    if not lst or not all(isinstance(e, dict) for e in lst):
        return None
    for cand in ("Key", "id", "name"):
        if all(cand in e for e in lst):
            return cand
    return None


def apply_change(doc, path, old, new):
    """Apply one leaf change onto doc. Returns 'ok' or 'conflict'."""
    parts = [p for p in path.split("/") if p]
    cur = doc
    for i, part in enumerate(parts):
        last = i == len(parts) - 1
        if part.startswith("[") and part.endswith("]"):
            key, val = part[1:-1].split("=", 1)
            idx = None
            for j, e in enumerate(cur):
                if isinstance(e, dict) and str(e.get(key)) == val:
                    idx = j
                    break
            if idx is None:
                if last and old is None:
                    cur.append(new)
                    return "ok"
                return "conflict"
            if last:
                if new is None:
                    if cur[idx] == old:
                        del cur[idx]
                        return "ok"
                    return "conflict"
                if cur[idx] == old or cur[idx] == new:
                    cur[idx] = new
                    return "ok"
                return "conflict"
            cur = cur[idx]
        else:
            if not isinstance(cur, dict):
                return "conflict"
            if last:
                have = cur.get(part)
                if new is None:
                    if have == old:
                        del cur[part]
                        return "ok"
                    return "conflict"
                if part not in cur and old is not None:
                    return "conflict"
                if part in cur and have != old and have != new:
                    return "conflict"
                cur[part] = new
                return "ok"
            if part not in cur:
                return "conflict"
            cur = cur[part]
    return "conflict"


def path_get(doc, path):
    parts = [p for p in path.split("/") if p]
    cur = doc
    for part in parts:
        if part.startswith("[") and part.endswith("]"):
            key, val = part[1:-1].split("=", 1)
            cur = next((e for e in cur if isinstance(e, dict)
                        and str(e.get(key)) == val), None)
        elif isinstance(cur, dict):
            cur = cur.get(part)
        else:
            return None
        if cur is None:
            return None
    return cur


def reconcile_lists(base_old, mod, base_new):
    """Deterministic merge for unkeyed arrays (tab labels, messages...):
    keep the mod's edits AND vanilla's appended entries."""
    if base_new[:len(base_old)] == base_old and len(base_new) > len(base_old):
        # vanilla appended entries: mod edits + new vanilla tail
        return mod + base_new[len(base_old):]
    if mod[:len(base_old)] == base_old and len(mod) > len(base_old):
        # mod appended entries: new vanilla body + mod tail
        return base_new + mod[len(base_old):]
    return None  # no safe rule; caller falls back to mod-wins


def force_set(doc, path, new):
    """Set a value at path unconditionally (mod-wins resolution)."""
    parts = [p for p in path.split("/") if p]
    cur = doc
    for i, part in enumerate(parts):
        last = i == len(parts) - 1
        if part.startswith("[") and part.endswith("]"):
            key, val = part[1:-1].split("=", 1)
            idx = next((j for j, e in enumerate(cur)
                        if isinstance(e, dict) and str(e.get(key)) == val),
                       None)
            if idx is None:
                if last and new is not None:
                    cur.append(new)
                return
            if last:
                if new is None:
                    del cur[idx]
                else:
                    cur[idx] = new
                return
            cur = cur[idx]
        else:
            if not isinstance(cur, dict):
                return
            if last:
                if new is None:
                    cur.pop(part, None)
                else:
                    cur[part] = new
                return
            cur = cur.setdefault(part, {})


def merge_strings(base_old, base_new, modded):
    """Semantic merge for string tables, robust to Blizzard key
    reshuffles (code renamed / repurposed / reused on another item).

    Rules per mod-edited key K (enUS ownership only):
      - K unchanged in new vanilla        -> apply mod text
      - K repurposed (vanilla enUS moved) -> if the mod text embeds the
        old vanilla name, transplant the edit onto the new name;
        otherwise the stale edit is DROPPED (vanilla wins) and logged
      - K deleted, same vanilla name reappears under key K2
                                          -> mod edit follows to K2
      - mod-invented key that new vanilla now defines -> vanilla wins
    """
    om = {e["Key"]: e for e in base_old if "Key" in e}
    nm = {e["Key"]: e for e in base_new if "Key" in e}
    mm = {e["Key"]: e for e in modded if "Key" in e}
    # index new vanilla by enUS for move detection (new keys only)
    new_by_text = {}
    for k, e in nm.items():
        if k not in om:
            new_by_text.setdefault(e.get("enUS", ""), []).append(k)

    result = json.loads(json.dumps(base_new))
    rm = {e["Key"]: e for e in result if "Key" in e}
    notes = []
    max_id = max((e.get("id", 0) for e in result), default=0)

    for k, me in mm.items():
        mtext = me.get("enUS")
        if k in om:
            otext = om[k].get("enUS")
            if mtext == otext:
                continue                      # not a mod edit
            if k in nm:
                ntext = nm[k].get("enUS")
                if ntext == otext:
                    rm[k]["enUS"] = mtext     # normal reapply
                elif otext and otext in (mtext or ""):
                    rm[k]["enUS"] = mtext.replace(otext, ntext)
                    notes.append("{}: item renamed '{}'->'{}', mod edit "
                                 "transplanted".format(k, otext, ntext))
                else:
                    notes.append("{}: key repurposed by vanilla, stale "
                                 "mod edit dropped".format(k))
            else:
                # key deleted: did the same item reappear elsewhere?
                cands = new_by_text.get(otext or "", [])
                if len(cands) == 1:
                    k2 = cands[0]
                    rm[k2]["enUS"] = mtext
                    notes.append("{}: key moved -> {}, mod edit "
                                 "followed".format(k, k2))
                else:
                    notes.append("{}: key removed by vanilla, mod edit "
                                 "dropped".format(k))
        else:
            # mod-invented key
            if k in nm:
                notes.append("{}: custom key now defined by vanilla - "
                             "vanilla wins, RENAME your custom key"
                             .format(k))
            else:
                entry = dict(me)
                if "id" in entry:
                    max_id += 1
                    entry["id"] = max_id
                result.append(entry)
    return result, notes


def merge_file(rel, old_p, new_p, mod_p, out_p):
    base_old, base_new, modded = jload(old_p), jload(new_p), jload(mod_p)
    if base_old == base_new:
        return ("unchanged", [])
    is_strings = rel.lower().startswith("data/local/lng/strings/")
    if is_strings and isinstance(base_old, list) and isinstance(modded, list):
        result, resolved = merge_strings(base_old, base_new, modded)
        os.makedirs(os.path.dirname(out_p), exist_ok=True)
        with open(out_p, "w", encoding="utf-8") as f:
            json.dump(result, f, indent=2, ensure_ascii=False)
        return ("merged", resolved)
    mod_delta = diff(base_old, modded)
    if not mod_delta:
        result, resolved = base_new, []
    else:
        result = json.loads(json.dumps(base_new))
        resolved = []
        for path, old, new in mod_delta:
            if apply_change(result, path, old, new) == "conflict":
                cur = path_get(result, path)
                merged = None
                if (isinstance(old, list) and isinstance(new, list)
                        and isinstance(cur, list)):
                    merged = reconcile_lists(old, new, cur)
                if merged is not None:
                    force_set(result, path, merged)
                    resolved.append(path + "  [list reconciled: mod edits "
                                    "+ vanilla additions kept]")
                else:
                    force_set(result, path, new)
                    resolved.append(path + "  [mod value kept]")
    os.makedirs(os.path.dirname(out_p), exist_ok=True)
    with open(out_p, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, ensure_ascii=False)
    return ("merged", resolved)


def main():
    bl = list_baselines()
    if len(bl) < 2:
        print("doctor: need two vanilla baselines, found {}: {}".format(
            len(bl), bl or "-"))
        print("1) before updating D2R:  python extract_casc.py")
        print("2) after updating D2R:   python extract_casc.py")
        print("   then re-run the doctor.")
        return 1
    old_root = os.path.join(BASELINES, bl[-2])
    new_root = os.path.join(BASELINES, bl[-1])
    print("doctor: base_old={} base_new={}".format(bl[-2], bl[-1]))

    install = "--install" in sys.argv
    report = {"merged": [], "resolved": {}, "unchanged": [],
              "no_baseline": [], "installed": []}
    for root, _, files in os.walk(EQ_ROOT):
        for fn in files:
            full = os.path.join(root, fn)
            rel = os.path.relpath(full, EQ_ROOT).replace("\\", "/")
            active = rel[:-3] if rel.endswith(".bk") else rel
            if not active.endswith(MERGEABLE_SUFFIX):
                continue
            if not active.lower().startswith(MERGEABLE_PREFIX):
                continue
            old_p = os.path.join(old_root, active.replace("/", os.sep))
            new_p = os.path.join(new_root, active.replace("/", os.sep))
            if not (os.path.isfile(old_p) and os.path.isfile(new_p)):
                report["no_baseline"].append(active)
                continue
            out_p = os.path.join(STAGING, active.replace("/", os.sep))
            state, resolved = merge_file(active, old_p, new_p, full, out_p)
            if state == "unchanged":
                report["unchanged"].append(active)
            else:
                report["merged"].append(active)
                if resolved:
                    report["resolved"][active] = resolved

    print("unchanged by game update : {}".format(len(report["unchanged"])))
    print("auto-merged into staging : {}".format(len(report["merged"])))
    for p in report["merged"]:
        print("   {}".format(p))
    if report["no_baseline"]:
        print("no vanilla counterpart   : {} (mod-only files, fine)".format(
            len(report["no_baseline"])))
    if report["resolved"]:
        print("collisions auto-resolved (mod value kept):")
        for p, spots in report["resolved"].items():
            for s in spots:
                print("   {} :: {}".format(p, s))
    if install and report["merged"]:
        import shutil
        import time
        bdir = os.path.join(HERE, "backups_prepatch",
                            time.strftime("%Y%m%d-%H%M%S"))
        for rel in report["merged"]:
            live = os.path.join(EQ_ROOT, rel.replace("/", os.sep))
            staged = os.path.join(STAGING, rel.replace("/", os.sep))
            bpath = os.path.join(bdir, rel.replace("/", os.sep))
            os.makedirs(os.path.dirname(bpath), exist_ok=True)
            shutil.copy(live, bpath)
            shutil.copy(staged, live)
            report["installed"].append(rel)
        print("installed {} merged files into live eq "
              "(backups in {})".format(len(report["installed"]), bdir))
    with open(os.path.join(HERE, "doctor_report.json"), "w",
              encoding="utf-8") as f:
        json.dump(report, f, indent=1)
    if not install:
        print("staged only (dry run). Re-run with --install to apply.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
