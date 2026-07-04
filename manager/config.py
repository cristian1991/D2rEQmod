"""Game/mod path resolution for eqtool.

Order: eqtool_config.json next to the tool -> EQTOOL_GAME env var ->
Windows uninstall registry -> common install paths. The resolved path
is cached back into eqtool_config.json so discovery runs once.
"""
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
CFG = os.path.join(HERE, "eqtool_config.json")
MOD_NAME = "eq"


def _candidates():
    yield os.environ.get("EQTOOL_GAME") or ""
    try:
        import winreg
        for hive, key in [
            (winreg.HKEY_LOCAL_MACHINE,
             r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion"
             r"\Uninstall\Diablo II Resurrected"),
            (winreg.HKEY_LOCAL_MACHINE,
             r"SOFTWARE\Microsoft\Windows\CurrentVersion"
             r"\Uninstall\Diablo II Resurrected"),
        ]:
            try:
                with winreg.OpenKey(hive, key) as k:
                    yield winreg.QueryValueEx(k, "InstallLocation")[0]
            except OSError:
                pass
    except ImportError:
        pass
    for root in ("C:", "D:", "E:", "F:"):
        yield root + r"\Games\Diablo II Resurrected"
        yield root + r"\Program Files (x86)\Diablo II Resurrected"
        yield root + r"\Diablo II Resurrected"


def _valid(p):
    return p and os.path.isfile(os.path.join(p, "D2R.exe"))


def game_root():
    try:
        cfg = json.load(open(CFG, encoding="utf-8"))
        if _valid(cfg.get("game_root")):
            return cfg["game_root"]
    except OSError:
        cfg = {}
    for c in _candidates():
        if _valid(c):
            cfg["game_root"] = c
            try:
                json.dump(cfg, open(CFG, "w", encoding="utf-8"), indent=1)
            except OSError:
                pass
            return c
    return None


GAME_ROOT = game_root()
GAME_EXE = os.path.join(GAME_ROOT, "D2R.exe") if GAME_ROOT else None
EQ_ROOT = (os.path.join(GAME_ROOT, "mods", MOD_NAME, MOD_NAME + ".mpq")
           if GAME_ROOT else None)
