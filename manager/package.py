"""Build the distributable EQ Mod Manager zip.

Layout of the package:
  EQ Mod Manager.exe    tiny C# launcher (compiled here via csc)
  runtime/              official python.org embeddable runtime (~18 MB)
  manager/              the tool: scripts, CascLib.dll, fonts, sprites,
                        icons, patch snapshots
  README.txt

Heavy Blizzard-derived media (video, music, vanilla baselines, favicon)
is NOT packaged: the tool extracts it from the user's own game install
on first run.
"""
import io
import os
import shutil
import subprocess
import sys
import urllib.request
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
DIST = os.path.join(HERE, "dist")
STAGE = os.path.join(DIST, "EQ Mod Manager")

PY_EMBED_URL = ("https://www.python.org/ftp/python/3.12.8/"
                "python-3.12.8-embed-amd64.zip")

MANAGER_FILES = [
    "eqtool_gui.py", "eqtool.py", "config.py", "casc.py",
    "patches.py", "layouts.py", "doctor.py", "extract_casc.py",
    "scan_features.py", "CascLib.dll",
]
MANAGER_DIRS = ["fonts", "sprites", "patches", "screenshots"]
SPRITE_EXCLUDE = (".sprite", "_useredit_backup", "_generated",
                  "buttonmed_sheet")


def clean():
    if os.path.isdir(STAGE):
        shutil.rmtree(STAGE)
    os.makedirs(STAGE, exist_ok=True)


def compile_launcher():
    csc = None
    for base in (r"C:\Windows\Microsoft.NET\Framework64",
                 r"C:\Windows\Microsoft.NET\Framework"):
        if os.path.isdir(base):
            for v in sorted(os.listdir(base), reverse=True):
                c = os.path.join(base, v, "csc.exe")
                if os.path.isfile(c):
                    csc = c
                    break
        if csc:
            break
    if not csc:
        raise SystemExit("csc.exe not found")
    out = os.path.join(STAGE, "EQ Mod Manager.exe")
    args = [csc, "/nologo", "/target:winexe", "/out:" + out,
            "/r:System.Windows.Forms.dll",
            os.path.join(HERE, "launcher.cs")]
    ico = os.path.join(HERE, "eqtool.ico")
    if os.path.isfile(ico):
        args.insert(4, "/win32icon:" + ico)
    r = subprocess.run(args, capture_output=True, text=True)
    if r.returncode:
        raise SystemExit(r.stdout + r.stderr)
    print("launcher compiled ->", out)


def fetch_runtime():
    rt = os.path.join(STAGE, "runtime")
    os.makedirs(rt, exist_ok=True)
    cache = os.path.join(DIST, "python-embed.zip")
    if not os.path.isfile(cache):
        print("downloading embeddable python ...")
        urllib.request.urlretrieve(PY_EMBED_URL, cache)
    with zipfile.ZipFile(cache) as z:
        z.extractall(rt)
    # the embeddable ._pth locks sys.path: add the manager dir so
    # sibling-module imports work for subprocess-launched scripts too
    for fn in os.listdir(rt):
        if fn.endswith("._pth"):
            with open(os.path.join(rt, fn), "a") as f:
                f.write("..\\manager\n")
    print("runtime ready ({} files)".format(len(os.listdir(rt))))


def copy_manager():
    mg = os.path.join(STAGE, "manager")
    os.makedirs(mg, exist_ok=True)
    for f in MANAGER_FILES:
        shutil.copy(os.path.join(HERE, f), mg)
    for d in MANAGER_DIRS:
        src = os.path.join(HERE, d)
        dst = os.path.join(mg, d)
        if not os.path.isdir(src):
            os.makedirs(dst, exist_ok=True)
            continue
        os.makedirs(dst, exist_ok=True)
        for root, _, files in os.walk(src):
            for fn in files:
                if any(x in fn for x in SPRITE_EXCLUDE):
                    continue
                rel = os.path.relpath(os.path.join(root, fn), src)
                out = os.path.join(dst, rel)
                os.makedirs(os.path.dirname(out), exist_ok=True)
                shutil.copy(os.path.join(root, fn), out)
    print("manager copied")


def write_readme():
    open(os.path.join(STAGE, "README.txt"), "w", encoding="utf-8").write(
        "EQ Mod Manager\n"
        "==============\n\n"
        "1. Install the eq mod folder into <D2R>/mods/eq/eq.mpq\n"
        "2. Double-click 'EQ Mod Manager.exe'\n"
        "   (first run pulls video/music/baselines from YOUR game\n"
        "    install - nothing Blizzard-owned ships in this zip)\n"
        "3. Toggle mod options, hit Install Mod, play.\n\n"
        "The manager needs Diablo II Resurrected installed. Game\n"
        "location is auto-detected; override in manager/eqtool_config.json\n")


def zip_dist():
    out = os.path.join(DIST, "EQ-Mod-Manager.zip")
    if os.path.isfile(out):
        os.remove(out)
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for root, _, files in os.walk(STAGE):
            for fn in files:
                p = os.path.join(root, fn)
                z.write(p, os.path.relpath(p, DIST))
    print("package:", out, "%.1f MB" % (os.path.getsize(out) / 1e6))


if __name__ == "__main__":
    clean()
    compile_launcher()
    fetch_runtime()
    copy_manager()
    write_readme()
    zip_dist()
