"""eqtool GUI - local visual panel for eq mod options.

Run:  python eqtool_gui.py     (opens http://localhost:8137 in browser)

Design based on d2r_mod_panel_template.html (project root).
Feature screenshots go in screenshots/ as <feature>_on.png and
<feature>_off.png (jpg/webp fine): both -> comparison slider,
one -> single shot, none -> status card.
Toggles apply real .bk renames after confirm; journaled to renames.log.
"""
import json
import mimetypes
import os
import subprocess
import sys
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import eqtool  # noqa: E402  (reuse rescan/set_feature/game_version/journal)
import patches  # noqa: E402  (key-group patch toggles for shared files)
import layouts  # noqa: E402  (layout-node patch toggles)

PORT = 8137
MOD_VERSION = "1.1.0"
SHOTS = os.path.join(HERE, "screenshots")

# variant option: one live file swapped between two shipped versions
# (ON = variant file, OFF = default file). Experimental transplants.
VARIANTS = {
    "coa-crown-float": {
        "live": os.path.join(eqtool.EQ_ROOT, "data", "hd", "items",
                             "armor", "circlet", "eq_coa.json"),
        "on": "eq_coa.float.json",
        "off": "eq_coa.seated.json",
        "desc": "Crown of Ages: floating crown hovers above the head "
                "(ON) or sits on it like a worn crown (OFF).",
        "label": "data/hd/items/armor/circlet/eq_coa.json  (variant swap)",
        "parent": "coa-crown",
        "title": "Floating crown",
        "on_label": "Floating above head",
        "off_label": "Seated on head",
        "view_on": "float",       # gallery view auto-selected per mode
        "view_off": "seated",
    },
}
VARIANT_DIR = os.path.join(HERE, "patches", "variants")


def _variant_live(v):
    # the parent feature may have the file parked as .bk while disabled;
    # the variant swap still applies so the choice survives re-enabling
    if os.path.isfile(v["live"]):
        return v["live"]
    if os.path.isfile(v["live"] + ".bk"):
        return v["live"] + ".bk"
    return v["live"]


def variant_state(name):
    v = VARIANTS[name]
    try:
        live = open(_variant_live(v), "rb").read()
        on = open(os.path.join(VARIANT_DIR, v["on"]), "rb").read()
        return "ON" if live == on else "OFF"
    except OSError:
        return "OFF"


def variant_set(name, enable):
    v = VARIANTS[name]
    src = os.path.join(VARIANT_DIR, v["on" if enable else "off"])
    import shutil
    shutil.copy(src, _variant_live(v))


# composite option: one switch driving several underlying features
# (rename-type members + patch-group members), hidden individually
COMPOSITES = {
    "npc-nameplates": {
        "renames": ["npc-glow", "npc-dialog-style"],
        "patches": ["npc-names"],
        "layouts": ["npc-vars"],
    },
    "drop-effects": {
        "renames": ["floor-effects", "light-pillars"],
        "patches": [], "layouts": [],
    },
    "custom-orbs": {
        "renames": ["pro-bars"],
        "patches": [], "layouts": ["orbs-hud", "hud-tweaks"],
    },
    "item-info-panels": {
        "renames": ["ui-sprites"],
        "patches": ["panel-texts"], "layouts": ["info-buttons"],
    },
    "cube-convert-button": {
        "renames": [], "patches": [], "layouts": ["cube-convert"],
    },
    "compact-windows": {
        "renames": [], "patches": [], "layouts": ["compact-windows"],
    },
    # the two monster-bar options share hudmonsterhealthhd.json but own
    # disjoint nodes — they can both be ON at the same time
    "monster-topbar": {
        "renames": [], "patches": [], "layouts": ["monster-topbar"],
    },
    "overhead-healthbars": {
        "renames": [], "patches": [], "layouts": ["overhead-bars"],
    },
}
_HIDDEN = {m for c in COMPOSITES.values()
           for m in c["renames"] + c["patches"]}
# these files stay live permanently; their content is managed at node
# level by the layout groups above
_NEVER_RENAME = {"hud-panel", "inventory-panels", "ui-profiles",
                 "hud-monster-health"}

BNET_CONFIG = os.path.expandvars(r"%APPDATA%\Battle.net\Battle.net.config")
MOD_ARGS = "-mod eq -txt"
SHORTCUT = os.path.join(os.path.expanduser("~"), "Desktop",
                        "Diablo II Resurrected - eq mod.lnk")


def bnet_running():
    try:
        r = subprocess.run(
            ["tasklist", "/FI", "IMAGENAME eq Battle.net.exe", "/FO", "CSV"],
            capture_output=True, text=True, timeout=15,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        return "Battle.net.exe" in r.stdout
    except Exception:
        return False


def mod_install_state():
    """installed = launch args persisted (Battle.net config if present,
    else desktop shortcut)."""
    if os.path.isfile(BNET_CONFIG):
        try:
            with open(BNET_CONFIG, encoding="utf-8-sig") as f:
                cfg = json.load(f)
            args = (cfg.get("Games", {}).get("osi", {})
                    .get("AdditionalLaunchArguments", ""))
            return ("bnet", MOD_ARGS in args)
        except Exception:
            return ("bnet", False)
    return ("shortcut", os.path.isfile(SHORTCUT))


def mod_install(install):
    mode, _ = mod_install_state()
    if mode == "bnet":
        with open(BNET_CONFIG, encoding="utf-8-sig") as f:
            cfg = json.load(f)
        osi = cfg.setdefault("Games", {}).setdefault("osi", {})
        cur = osi.get("AdditionalLaunchArguments", "")
        if install:
            if MOD_ARGS not in cur:
                osi["AdditionalLaunchArguments"] = \
                    (cur + " " + MOD_ARGS).strip()
        else:
            osi["AdditionalLaunchArguments"] = \
                cur.replace(MOD_ARGS, "").strip()
        with open(BNET_CONFIG, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=1)
        return ("Battle.net launch arguments {} (close Battle.net first "
                "or it may overwrite the setting on exit).".format(
                    "set: " + MOD_ARGS if install else "cleared"))
    if install:
        ps = (
            "$s=(New-Object -ComObject WScript.Shell)"
            ".CreateShortcut('{lnk}');"
            "$s.TargetPath='{exe}';"
            "$s.Arguments='{args}';"
            "$s.WorkingDirectory='{cwd}';$s.Save()"
        ).format(lnk=SHORTCUT, exe=eqtool.GAME_EXE, args=MOD_ARGS,
                 cwd=os.path.dirname(eqtool.GAME_EXE))
        subprocess.run(["powershell", "-NoProfile", "-Command", ps],
                       capture_output=True, timeout=30,
                       creationflags=getattr(subprocess,
                                             "CREATE_NO_WINDOW", 0))
        return "Desktop shortcut created: launches D2R with " + MOD_ARGS
    if os.path.isfile(SHORTCUT):
        os.remove(SHORTCUT)
    return "Desktop shortcut removed - D2R launches vanilla."


FONTS = {
    "exocet": [os.path.join(HERE, "fonts", "exocet.woff")],
    "global": [os.path.join(HERE, "fonts", "global.woff")],
}

DESCRIPTIONS = {
    "better-runes": "Improved rune sprites and visibility.",
    "floor-effects": "ESP item-filter floor effects for runes, gems, keys and charms.",
    "golden-cursor": "Golden Gauntlet mouse cursor.",
    "hud-monster-health": "Monster HP bar layout tweaks: transparency, larger font.",
    "hud-panel": "Custom HUD panel: centered orb wiring and pro-bar toggle actions.",
    "intro-videos": "Replaced logo and intro videos. Disable for vanilla startup.",
    "inventory-panels": "Custom inventory layouts with item-info buttons and detail panels.",
    "light-pillars": "Light pillar drop effects for runes and gems.",
    "main-menu-layout": "Main menu difficulty and settings placement (yupgoolg).",
    "npc-dialog-style": "Nicer NPC dialogue text panel styling (yupgoolg).",
    "npc-glow": "NPC under-name glow and particles plus nickname icons (size-pruned).",
    "pro-bars": "HP and mana pro-bar popups on orb click.",
    "panel-texts": "Custom item-info and HUD panel texts (weapon, helm, shield details).",
    "npc-names": "Styled NPC names and titles (yupgoolg nickname look).",
    "npc-nameplates": "Custom NPC nameplates: under-name glow and icons, "
                      "styled dialog panel, nameplate-driven names.",
    "drop-effects": "Custom drop and on-floor effects for runes, gems, "
                    "keys, charms and body parts.",
    "custom-orbs": "Custom HUD: centered health/mana globes with "
                   "click-to-toggle resource bars, repositioned skill "
                   "buttons, belt and bars.",
    "item-info-panels": "Item detail buttons and reference panels in the "
                        "inventory, with custom panel art.",
    "cube-convert-button": "Cube transmute button inside the inventory - "
                           "no reaching across the screen.",
    "compact-windows": "Slimmer open windows: side panels and hinges "
                       "removed, panels pushed to the screen edges.",
    "monster-topbar": "Custom top-of-screen monster health bar.",
    "overhead-healthbars": "EXPERIMENTAL: console-style health bars above "
                           "monsters, transplanted to PC mode.",
    "item-icons-and-nameplates": "Item icons and nameplates: icon glyphs, name "
                  "shorthand and big clickable plates for high runes.",
    "ui-profiles": "UI profile geometry: centered orbs, side panels removed.",
    "ui-sprites": "Custom panel sprite art for HUD, inventory and waypoints.",
    "trav-wall-remove": "Travincal wall removal.",
    "coa-crown": "Crown of Ages only: custom open-top golden crown (own 3D model + texture). Regular crowns and diadems stay vanilla.",
    "waypoint-lights": "Horadric waypoint light beams and automap markers.",
    "core-modinfo": "Mod bootstrap file. Cannot be disabled.",
}
# Icon glyphs from the eq-modified Exocet font (custom circled icons
# remapped over superscript/subscript/Roman-numeral codepoints — the
# same trick the mod's item names use).
ICONS = {
    "better-runes": "ₘ",       # rune circle
    "core-modinfo": "º",       # crossed circle
    "floor-effects": "¾",      # gem
    "fonts": "Ⅹ",              # tome/book
    "golden-cursor": "₎",      # gauntlet
    "hud-monster-health": "¼", # skull
    "hud-panel": "⅒",          # shield
    "intro-videos": "₅",       # sparkles
    "inventory-panels": "Ⅰ",   # armor torso
    "light-pillars": "₆",      # star
    "main-menu-layout": "ⁿ",   # crown
    "npc-dialog-style": "₊",   # figure
    "npc-glow": "₈",           # pentacle
    "pro-bars": "Ⅷ",           # potion
    "show-item-level": "ⁱ",    # coin
    "panel-texts": "Ⅸ",        # scroll
    "npc-names": "Ⅶ",          # wings
    "npc-nameplates": "₈",     # pentacle (nameplate glow)
    "drop-effects": "¾",       # gem
    "overhead-healthbars": "¼",  # skull
    "custom-orbs": "Ⅷ",          # potion/orb
    "item-info-panels": "Ⅸ",     # scroll
    "cube-convert-button": "Ⅺ",  # cube-ish
    "compact-windows": "⅒",      # shield/panel
    "hud-tweaks": "⅑",           # gear
    "monster-topbar": "º",       # bar
    "npc-vars": "",
    "orbs-hud": "", "info-buttons": "", "cube-convert": "",
    "item-icons-and-nameplates": "ⁱ",         # coin
    "ui-profiles": "⅑",        # gear
    "ui-sprites": "₃",         # frame
    "trav-wall-remove": "⅙",        # pickaxe
    "coa-crown": "ⁿ",             # crown
    "waypoint-lights": "Ⅻ",    # charm/portal
}

PAGE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>eq &mdash; Mod Options</title>
<link rel="icon" href="/favicon.ico">
<style>
@font-face{font-family:"ExocetBlizzard";
 src:url("/fonts/exocet") format("woff");font-display:swap;}
@font-face{font-family:"BlizzardGlobal";
 src:url("/fonts/global") format("woff");font-display:swap;}
:root {
  --bg:#080604; --panel:#17100b; --gold:#b68a3a; --gold-bright:#e0be73;
  --blood:#7b1412; --green:#5f8f48; --text:#d8c39b; --muted:#8b7653;
  --line:rgba(224,190,115,.32);
  --font-ui:"ExocetBlizzard",Georgia,"Times New Roman",serif;
  --font-small:"ExocetBlizzard",Georgia,"Times New Roman",serif;
  --font-glyph:"BlizzardGlobal","Trebuchet MS",Arial,sans-serif;
}
*{box-sizing:border-box}
html,body{height:100%;margin:0;color:var(--text);font-family:var(--font-small);
 overflow:hidden;background:
  radial-gradient(circle at 50% 8%, rgba(115,28,20,.34), transparent 34rem),
  radial-gradient(circle at 18% 28%, rgba(182,138,58,.10), transparent 24rem),
  radial-gradient(circle at 82% 62%, rgba(91,20,16,.24), transparent 30rem),
  linear-gradient(145deg,#050302,#100905 42%,#070403);}
.app-shell{width:min(1420px,calc(100vw - 32px));height:calc(100vh - 32px);
 display:flex;flex-direction:column;
 margin:16px auto;border:1px solid #4a4a50;position:relative;overflow:hidden;
 z-index:1;outline:2px solid rgba(0,0,0,.9);
 opacity:0;transition:opacity .7s ease;}
.app-shell.ready{opacity:1;}
.app-shell{
 background:rgba(8,8,10,.52);
 box-shadow:0 0 0 4px rgba(30,30,34,.65),0 0 0 5px rgba(0,0,0,.8),
  0 22px 70px rgba(0,0,0,.8),inset 0 0 80px rgba(0,0,0,.55);}
.topbar{position:relative;z-index:2;min-height:150px;display:grid;
 grid-template-columns:auto 1fr auto;align-items:end;gap:10px;
 padding:6px 26px 0;border-bottom:1px solid #2c2c31;
 background:linear-gradient(180deg,rgba(0,0,0,.5),rgba(0,0,0,.15));}
.topbar>.title-box{align-self:center;padding-top:27px;}
.title{text-align:center;letter-spacing:.18em;text-transform:uppercase;
 font-family:var(--font-ui);
 text-shadow:0 2px 0 #000,0 0 16px rgba(224,190,115,.20);
 color:var(--gold-bright);line-height:1;}
.title strong{display:block;font-size:clamp(1.8rem,3vw,3rem);font-weight:500;
 font-variant:small-caps;letter-spacing:.14em;
 background:linear-gradient(180deg,#fff3cf 0%,#f2d795 30%,#e0be73 55%,#c89a4e 78%,#e8cd8d 100%);
 -webkit-background-clip:text;background-clip:text;-webkit-text-fill-color:transparent;
 filter:drop-shadow(0 2px 2px rgba(0,0,0,.9)) drop-shadow(0 0 4px rgba(0,0,0,.8))
  drop-shadow(0 0 18px rgba(255,180,80,.35));}
.title span{display:block;margin-top:8px;font-family:var(--font-small);
 font-size:.72rem;color:var(--muted);letter-spacing:.34em;}
.status-strip{display:flex;align-items:center;gap:10px;font-family:var(--font-small);
 font-size:.8rem;text-transform:uppercase;letter-spacing:.1em;color:var(--muted);}
.status-strip.right{justify-self:end;}
/* statue + animated liquid globe (46-frame strip from the eq HUD orb;
   demon stays red, angel hue-rotated blue like the hud json does) */
.statue-wrap{position:relative;flex:none;z-index:3;height:166px;
 display:block;margin:0;pointer-events:none;
 filter:drop-shadow(0 6px 10px rgba(0,0,0,.85));}
.statue{height:100%;width:auto;position:relative;z-index:2;display:block;}
.globe-liquid{position:absolute;z-index:1;border-radius:50%;
 background:url("/sprites/orb_liquid_strip.png") 0 0/4600% 100%;
 animation:orbAnim 3.2s steps(45) infinite;}
.statue-wrap.angel .globe-liquid{width:138.4px;height:138.4px;
 left:102.8px;top:25.2px;filter:hue-rotate(230deg) saturate(1.1);}
.statue-wrap.demon .globe-liquid{width:138.4px;height:138.4px;
 left:22px;top:25.2px;}
@keyframes orbAnim{from{background-position:0 0}to{background-position:100% 0}}
.orb{width:42px;height:42px;border-radius:50%;flex:none;
 background:radial-gradient(circle at 36% 30%, rgba(255,255,255,.22), transparent 12%),
  radial-gradient(circle at 50% 60%, #9b1b17, #3c0908 62%, #110403 100%);
 border:1px solid rgba(224,190,115,.45);
 box-shadow:0 0 18px rgba(183,37,31,.32),inset 0 -7px 16px rgba(0,0,0,.68);}
.orb.blue{background:radial-gradient(circle at 36% 30%, rgba(255,255,255,.25), transparent 12%),
  radial-gradient(circle at 50% 60%, #1b3f9b, #081c3c 62%, #030811 100%);
 box-shadow:0 0 18px rgba(31,80,183,.32),inset 0 -7px 16px rgba(0,0,0,.68);}
.updwarn{position:relative;z-index:2;margin:14px 34px 0;padding:12px 18px;
 border:1px solid rgba(183,37,31,.65);background:rgba(91,20,16,.30);
 color:#e0b3a3;font-family:var(--font-small);font-size:.86rem;display:none;
 box-shadow:inset 0 0 22px rgba(0,0,0,.5);}
.updwarn button{margin-left:14px;}
.layout{position:relative;z-index:2;display:grid;
 grid-template-columns:310px minmax(0,1fr);flex:1;min-height:0;}
.sidebar{padding:20px 18px 20px 28px;border-right:1px solid #2c2c31;
 display:flex;flex-direction:column;overflow:hidden;min-height:0;
 background:rgba(7,7,9,.55);}
.section-label{margin:0 0 14px;color:var(--gold-bright);
 font-variant:small-caps;letter-spacing:.16em;
 font-family:var(--font-ui);font-size:.92rem;
 border-bottom:1px solid #2c2c31;padding-bottom:8px;}
.mod-list{display:grid;gap:8px;margin-bottom:16px;align-content:start;
 flex:1;min-height:0;overflow-y:auto;padding-right:8px;}
.sidebar>.section-label,.sidebar>.sidebar-note{flex:none;}
/* D2R HD scrollbar: slim steel channel with rounded caps, gold knob */
.d2scroll::-webkit-scrollbar{width:13px;}
.d2scroll::-webkit-scrollbar-track{
 background:linear-gradient(90deg,#0a0a0c,#17171a 50%,#0a0a0c);
 border:1px solid #45454c;border-radius:7px;
 box-shadow:inset 0 0 8px #000,inset 0 2px 4px rgba(0,0,0,.8),
  0 0 0 1px #0a0806;}
.d2scroll::-webkit-scrollbar-thumb{
 background:
  linear-gradient(180deg,rgba(255,246,214,.55),transparent 40%),
  linear-gradient(90deg,#7d6228,#e0be73 45%,#c8a35a 55%,#6d5426);
 border:1px solid #2a1e0c;border-radius:5px;min-height:34px;
 box-shadow:inset 0 1px 0 rgba(255,246,214,.5),inset 0 -2px 3px rgba(0,0,0,.55),
  0 0 6px rgba(0,0,0,.6);}
.d2scroll::-webkit-scrollbar-thumb:hover{filter:brightness(1.15);}
.d2scroll::-webkit-scrollbar-button:single-button{
 height:14px;background-color:transparent;
 background-repeat:no-repeat;background-position:center;background-size:8px 7px;}
.d2scroll::-webkit-scrollbar-button:single-button:vertical:decrement{
 background-image:url("data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' width='10' height='9'><path d='M5 0 L10 9 L0 9 Z' fill='%23c8a35a'/></svg>");}
.d2scroll::-webkit-scrollbar-button:single-button:vertical:increment{
 background-image:url("data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' width='10' height='9'><path d='M0 0 L10 0 L5 9 Z' fill='%23c8a35a'/></svg>");}
.d2scroll{scrollbar-width:thin;scrollbar-color:#b3903f #121214;}
.mod-tab{all:unset;cursor:pointer;display:grid;grid-template-columns:auto 1fr auto;
 align-items:center;gap:10px;padding:11px 12px;
 background:rgba(9,9,11,.72);
 border:1px solid #2c2c31;box-shadow:inset 0 0 18px rgba(0,0,0,.55);
 color:#cfc4ad;font-size:.92rem;text-shadow:0 1px 0 #000;
 transition:transform .12s ease,border-color .12s ease,background .12s ease;}
.mod-tab:hover,.mod-tab.active{border-color:#6a6a72;
 background:rgba(18,18,21,.85);
 box-shadow:inset 0 0 18px rgba(0,0,0,.55),inset 0 1px 0 rgba(255,255,255,.06),
  0 0 10px rgba(224,190,115,.08);
 transform:translateX(2px);}
.mod-tab.active{border-color:rgba(224,190,115,.55);}
.mod-tab small{font-family:var(--font-small);color:var(--muted);font-size:.66rem;
 text-transform:uppercase;letter-spacing:.12em;}
.rune{width:30px;height:30px;display:grid;place-items:center;flex:none;}
.rune img{width:24px;height:24px;display:block;
 filter:drop-shadow(0 1px 2px #000) drop-shadow(0 0 6px rgba(224,190,115,.2));}
.rune.off img{filter:grayscale(1) brightness(.55) drop-shadow(0 1px 2px #000);}
.file-row span:first-child{font-family:var(--font-glyph);font-size:.78rem;}
/* keybind-screen colors: assigned = gold, missing = red */
.pill{font-family:var(--font-small);font-size:.66rem;letter-spacing:.14em;
 font-variant:small-caps;border:none;padding:2px 4px;
 color:#e0be73;background:none;text-shadow:0 1px 1px #000;}
.pill.off{color:#c0392b;}
.pill.mixed{color:#9a8a6a;}
.sidebar-note{padding:15px;border:1px solid rgba(182,138,58,.22);
 background:rgba(0,0,0,.22);box-shadow:inset 0 0 22px rgba(0,0,0,.44);
 color:var(--muted);font-family:var(--font-small);font-size:.82rem;line-height:1.55;}
.content{padding:18px 30px 14px;display:flex;flex-direction:column;gap:14px;
 overflow:hidden;min-height:0;
 background:radial-gradient(circle at 76% 18%, rgba(224,190,115,.08), transparent 24rem),
  radial-gradient(circle at 38% 92%, rgba(123,20,18,.18), transparent 30rem);}
/* in-game options-screen panel look: near-black glass, steel edge */
.hero-card{display:grid;grid-template-columns:minmax(0,1fr) auto;gap:24px;
 align-items:center;padding:20px 24px;
 border:1px solid #3f3f44;outline:1px solid rgba(0,0,0,.85);
 background:rgba(9,9,11,.78);
 box-shadow:inset 0 0 40px rgba(0,0,0,.7),inset 0 1px 0 rgba(255,255,255,.04),
  0 10px 26px rgba(0,0,0,.45);}
.mod-title{margin:0;color:var(--gold-bright);font-size:clamp(1.4rem,2vw,2.1rem);
 font-weight:500;text-shadow:0 2px 0 #000,0 0 16px rgba(224,150,60,.2);
 font-variant:small-caps;letter-spacing:.12em;}
.mod-desc{max-width:72ch;margin:8px 0 0;color:#bca983;line-height:1.55;
 font-family:var(--font-small);font-size:.95rem;}
.actions{display:flex;flex-wrap:wrap;gap:10px;justify-content:flex-end;}
.hero-btn{min-width:170px;width:170px;box-sizing:border-box;}
#bgvid{position:fixed;inset:0;width:100vw;height:100vh;object-fit:cover;
 z-index:0;pointer-events:none;transform:scale(1);transform-origin:50% 46%;
 transition:transform 2.4s cubic-bezier(.25,.6,.3,1);}
#bgvid.zoomed{transform:scale(var(--bgzoom,1.7));}
.bg-shade{position:fixed;inset:0;z-index:0;pointer-events:none;
 background:radial-gradient(circle at 50% 35%, transparent 30%, rgba(5,3,2,.45) 80%);}
/* Genuine D2R frontend button art (frontend_buttonmed.sprite, decoded
   from the game's CASC): frame 0 normal, 1 pressed, 2 disabled, 3 hover.
   9-slice keeps the gold corners and blue orbs undistorted. */
.game-btn{all:unset;cursor:pointer;position:relative;min-width:150px;text-align:center;
 box-sizing:border-box;padding:14px 52px;color:#d3b775;font-family:var(--font-ui);
 font-variant:small-caps;letter-spacing:.2em;font-size:.98rem;
 text-shadow:0 2px 2px #000,0 0 8px rgba(0,0,0,.8);
 border:20px solid transparent;border-left-width:34px;border-right-width:34px;
 border-image:url("/sprites/frontend_buttonmed_f0.png") 50 86 fill stretch;
 filter:drop-shadow(0 6px 12px rgba(0,0,0,.6));padding:0 8px 4px;min-height:10px;}
.game-btn:hover{color:#f0dfae;
 border-image:url("/sprites/frontend_buttonmed_f3.png") 50 86 fill stretch;}
.game-btn:active{
 border-image:url("/sprites/frontend_buttonmed_f1.png") 50 86 fill stretch;}
.game-btn:disabled,.game-btn.locked{cursor:default;color:#6e6458;
 border-image:url("/sprites/frontend_buttonmed_f2.png") 50 86 fill stretch;}
.game-btn.secondary{display:block;width:100%;min-width:0;box-sizing:border-box;
 font-size:.8rem;color:#c2a878;letter-spacing:.12em;
 border-width:15px solid transparent;border-width:15px 26px;}
.game-btn.enabled{color:#e6d6a0;
 filter:drop-shadow(0 6px 12px rgba(0,0,0,.6)) drop-shadow(0 0 10px rgba(95,143,72,.3));}
.main-stack{flex:1;display:flex;flex-direction:column;gap:14px;min-height:0;}
.panel-grid{display:grid;grid-template-columns:1fr;
 grid-template-rows:minmax(0,1fr);gap:18px;min-height:0;flex:1;}
.preview-frame{display:flex;flex-direction:column;min-height:0;}
.preview-body{flex:1;display:flex;flex-direction:column;min-height:0;}
/* files drawer: slide-in over the right edge */
#filesDrawer{display:flex;flex-direction:column;min-height:0;
 position:fixed;top:186px;right:18px;bottom:20px;width:440px;z-index:6;
 background:rgba(8,8,10,.96);transform:translateX(120%);
 transition:transform .28s ease;box-shadow:-14px 0 40px rgba(0,0,0,.6);}
#filesDrawer.open{transform:none;}
.details-body{flex:1;min-height:0;overflow:hidden;display:flex;
 flex-direction:column;gap:14px;padding:16px;}
.drawer-close{all:unset;cursor:pointer;color:var(--gold-bright);
 font-size:1rem;padding:0 6px;}
.drawer-close:hover{color:#f0dfae;}
.preview-frame,.details-frame{min-height:0;
 border:1px solid #3f3f44;outline:1px solid rgba(0,0,0,.85);
 background:rgba(9,9,11,.78);
 box-shadow:inset 0 0 46px rgba(0,0,0,.72),inset 0 1px 0 rgba(255,255,255,.04);
 position:relative;}
.frame-heading{display:flex;align-items:center;justify-content:space-between;gap:12px;
 padding:13px 16px;border-bottom:1px solid #2c2c31;color:var(--gold-bright);
 font-variant:small-caps;letter-spacing:.14em;font-family:var(--font-ui);
 font-size:.92rem;background:rgba(0,0,0,.35);}
.frame-heading span:last-child{color:var(--muted);letter-spacing:.1em;}
.preview-body{padding:14px 14px 12px;}
.shot-stage{flex:1;width:100%;min-height:220px;
 border:1px solid #303036;overflow:hidden;position:relative;
 background:rgba(4,4,6,.7);
 box-shadow:inset 0 0 70px rgba(0,0,0,.8),0 0 0 2px rgba(0,0,0,.5);}
.placeholder-art{position:absolute;inset:0;display:grid;place-items:center;
 text-align:center;padding:28px;}
.placeholder-art div{position:relative;max-width:460px;padding:24px;
 border:1px solid rgba(182,138,58,.26);background:rgba(0,0,0,.38);
 box-shadow:inset 0 0 22px rgba(0,0,0,.65);}
.placeholder-art b{display:block;color:var(--gold-bright);font-weight:500;
 font-size:1.2rem;letter-spacing:.08em;text-transform:uppercase;}
.placeholder-art p{margin:10px 0 0;color:var(--muted);
 font-family:var(--font-small);line-height:1.45;}
.comparison{display:none;position:absolute;inset:0;--split:50%;}
.comparison.show{display:block;}
.comparison .shot-off,.comparison .shot-on{position:absolute;inset:0;
 background-size:cover;background-position:center;}
.comparison .shot-on{clip-path:polygon(0 0, var(--split) 0, var(--split) 100%, 0 100%);}
.split-line{position:absolute;top:0;left:var(--split);width:2px;height:100%;
 background:rgba(224,190,115,.88);box-shadow:0 0 16px rgba(224,190,115,.55);
 transform:translateX(-1px);}
.split-knob{position:absolute;left:var(--split);top:50%;width:44px;height:44px;
 border-radius:50%;border:1px solid rgba(224,190,115,.86);background:rgba(10,6,4,.88);
 transform:translate(-50%,-50%);display:grid;place-items:center;color:var(--gold-bright);
 box-shadow:0 0 22px rgba(0,0,0,.80),inset 0 0 14px rgba(224,190,115,.15);
 font-family:var(--font-small);font-size:.72rem;pointer-events:none;}
.compare-range{position:absolute;inset:0;opacity:0;cursor:ew-resize;width:100%;margin:0;}
.single-shot{display:none;position:absolute;inset:0;background-size:cover;
 background-position:center;cursor:zoom-in;}
.single-shot.show{display:block;}
.shot-labels{position:absolute;inset:14px 14px auto 14px;display:flex;
 justify-content:space-between;pointer-events:none;font-family:var(--font-small);
 font-size:.68rem;letter-spacing:.12em;text-transform:uppercase;
 color:var(--gold-bright);text-shadow:0 1px 0 #000,0 0 8px #000;}
.details-body{padding:16px;display:flex;flex-direction:column;gap:14px;}
.info-box.grow{flex:1;min-height:0;display:flex;flex-direction:column;}
.info-box.grow .file-list{flex:1;max-height:none;}
.info-box{border:1px solid #303036;background:rgba(6,6,8,.55);
 padding:16px;box-shadow:inset 0 0 24px rgba(0,0,0,.55);}
.info-box h3{margin:0 0 10px;color:var(--gold-bright);font-size:1.05rem;font-weight:500;
 font-variant:small-caps;letter-spacing:.1em;font-family:var(--font-ui);}
.info-box p,.info-box li{color:#bba47b;font-family:var(--font-small);
 font-size:.9rem;line-height:1.55;}
.info-box p{margin:0;}
.info-box ul{margin:0;padding-left:18px;}
.file-list{max-height:210px;overflow-y:auto;padding-right:8px;}
/* keybind-table look: white-ish names, gold values */
.file-row{display:grid;grid-template-columns:1fr auto;align-items:center;gap:10px;
 padding:8px 0;border-bottom:1px solid rgba(255,255,255,.05);
 font-family:var(--font-small);color:#e8e2d4;font-size:.82rem;word-break:break-all;}
.file-row:last-child{border-bottom:0;}
.tag{color:#e0be73;border:none;padding:2px 4px;
 font-size:.66rem;letter-spacing:.1em;font-variant:small-caps;
 background:none;flex:none;text-shadow:0 1px 1px #000;}
.tag.bk{color:#c0392b;}
.bottom-command{display:flex;justify-content:space-between;gap:18px;align-items:center;
 flex:none;margin-top:0;padding:13px 18px;border:1px solid rgba(224,190,115,.24);
 background:linear-gradient(90deg,rgba(123,20,18,.18),transparent 40%,rgba(224,190,115,.08)),
  rgba(0,0,0,.22);font-family:var(--font-small);color:var(--muted);}
.progress-glyphs{display:flex;gap:6px;flex-wrap:wrap;}
.glyph{width:16px;height:16px;border:1px solid rgba(182,138,58,.34);
 background:rgba(0,0,0,.35);transform:rotate(45deg);cursor:pointer;}
.glyph.on{background:rgba(95,143,72,.45);box-shadow:0 0 12px rgba(95,143,72,.25);}
.glyph.mixed{background:rgba(182,138,58,.45);}
#lightbox{position:fixed;inset:0;background:rgba(0,0,0,.92);display:none;
 align-items:center;justify-content:center;cursor:zoom-out;z-index:9;}
#lightbox img{max-width:96vw;max-height:96vh;border:1px solid rgba(224,190,115,.4);}
body.nobg{background:#000;}
body.nobg .bg-shade{display:none;}
#cornerCtrls{position:fixed;top:10px;right:16px;z-index:9;display:flex;gap:8px;}
.ctrl{all:unset;cursor:pointer;padding:5px 14px;color:#8b7653;
 font-family:var(--font-ui);font-variant:small-caps;letter-spacing:.14em;
 font-size:.74rem;border:1px solid #3f3f44;background:rgba(9,9,11,.8);
 box-shadow:inset 0 0 12px rgba(0,0,0,.6);text-shadow:0 1px 1px #000;}
.ctrl:hover{color:#e0be73;border-color:#6a6a72;}
.ctrl.on{color:#e0be73;border-color:rgba(224,190,115,.5);}
.variant-sel{appearance:none;-webkit-appearance:none;
 background:linear-gradient(180deg,#241a10,#150e08);color:var(--gold-bright);
 border:1px solid rgba(198,161,90,.55);box-shadow:inset 0 1px 0 rgba(255,255,255,.06),0 2px 6px rgba(0,0,0,.5);
 font-family:var(--font-head);letter-spacing:.06em;text-transform:uppercase;
 font-size:.8rem;padding:11px 34px 11px 14px;cursor:pointer;outline:none;
 background-image:linear-gradient(180deg,#241a10,#150e08),
   url("data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' width='10' height='6'><path d='M0 0l5 6 5-6z' fill='%23c6a15a'/></svg>");
 background-repeat:no-repeat,no-repeat;background-position:0 0,right 12px center;}
.variant-sel:hover{border-color:var(--gold-bright);}
.variant-sel option{background:#17100b;color:var(--text);
 font-family:var(--font-ui);text-transform:none;font-size:.9rem;}
.gallery-thumbs{position:absolute;left:10px;right:10px;bottom:10px;z-index:4;
 display:flex;gap:8px;flex-wrap:wrap;justify-content:center;pointer-events:auto;}
.gal-thumb{position:relative;width:96px;height:58px;background-size:cover;background-position:center;
 border:1px solid rgba(198,161,90,.35);cursor:pointer;filter:saturate(.75) brightness(.8);padding:0;}
.gal-thumb.active{border-color:var(--gold-bright);filter:none;}
.gal-thumb:hover{filter:none;}
.gal-thumb span{position:absolute;left:0;right:0;bottom:0;font-size:.62rem;
 font-family:var(--font-ui);font-variant:small-caps;letter-spacing:.08em;
 background:rgba(0,0,0,.65);color:var(--text);padding:1px 3px;text-align:center;}
#ghLink{position:fixed;left:22px;bottom:8px;z-index:2;
 display:flex;align-items:center;gap:8px;
 font-family:var(--font-ui);font-variant:small-caps;letter-spacing:.14em;
 font-size:.95rem;color:var(--muted);text-decoration:none;
 text-shadow:0 1px 2px #000;}
#ghLink svg{width:19px;height:19px;fill:currentColor;filter:drop-shadow(0 1px 2px #000);}
#ghLink:hover{color:var(--gold-bright);}
#modVer{position:fixed;right:22px;bottom:28px;z-index:2;
 font-family:var(--font-ui);font-variant:small-caps;letter-spacing:.18em;
 font-size:.95rem;color:var(--muted);text-shadow:0 1px 2px #000;}
#gameVer{position:fixed;right:22px;bottom:6px;z-index:2;
 font-family:var(--font-ui);font-variant:small-caps;letter-spacing:.18em;
 font-size:.95rem;color:var(--muted);text-shadow:0 1px 2px #000;}
#toast{position:fixed;left:50%;bottom:26px;transform:translateX(-50%);z-index:8;
 background:#17100b;border:1px solid rgba(224,190,115,.55);color:var(--text);
 padding:12px 22px;font-family:var(--font-small);font-size:.85rem;display:none;
 box-shadow:0 8px 30px rgba(0,0,0,.7);white-space:pre-wrap;max-width:80vw;}
@media (max-width:1050px){
 .layout{grid-template-columns:1fr;}
 .sidebar{border-right:0;border-bottom:1px solid var(--line);}
 .panel-grid{grid-template-columns:1fr;}
 .topbar{grid-template-columns:1fr;height:auto;text-align:center;}
 .status-strip,.status-strip.right{justify-self:center;}
 .hero-card{grid-template-columns:1fr;}
 .actions{justify-content:flex-start;}}
@media (max-width:620px){
 .app-shell{width:calc(100vw - 18px);margin:9px auto;}
 .content{padding:20px 16px;}
 .sidebar{padding:22px 16px;}
 .shot-stage{min-height:240px;}
 .bottom-command{flex-direction:column;align-items:flex-start;}}
</style>
</head>
<body>
<video id="bgvid" autoplay muted loop playsinline
  onerror="this.remove()" src="/bg.webm"></video>
<div class="bg-shade"></div>
<main class="app-shell">
  <header class="topbar">
    <div class="status-strip"><span class="statue-wrap angel"><span class="globe-liquid"></span><img class="statue" src="/sprites/orb_angel.png" alt=""></span></div>
    <div class="title-box">
      <div class="title"><strong>eq &mdash; Mod Options</strong></div>
    </div>
    <div class="status-strip right"><span class="statue-wrap demon"><span class="globe-liquid"></span><img class="statue" src="/sprites/orb_demon.png" alt=""></span></div>
  </header>

  <div class="updwarn" id="updWarn"></div>

  <section class="layout">
    <aside class="sidebar">
      <p class="section-label">Mod Options</p>
      <nav class="mod-list d2scroll" id="modList"></nav>
      <p class="section-label">Maintenance</p>
      <div style="display:grid;gap:10px;">
        <button class="game-btn secondary" id="installBtn"
          onclick="installMod()">Install Mod</button>
        <button class="game-btn secondary" onclick="launchGame()">Launch D2R &mdash; mod eq</button>
        <button class="game-btn secondary" onclick="runDoctor()">D2R Updated &mdash; Repair</button>
      </div>
    </aside>

    <section class="content d2scroll">
      <div class="hero-card">
        <div>
          <h1 class="mod-title" id="modTitle">Loading...</h1>
        </div>
        <div class="actions" style="flex-direction:column;align-items:flex-end;gap:6px;">
          <div style="display:flex;gap:12px;align-items:center;">
            <select id="variantSel" class="variant-sel" style="display:none;"
              onchange="variantChanged(this)"></select>
            <button class="game-btn hero-btn" id="filesBtn"
              onclick="toggleDrawer()">Files</button>
            <button class="game-btn hero-btn" id="toggleBtn"
              onclick="toggleSelected()">...</button>
          </div>
        </div>
      </div>

      <div class="main-stack">
        <div class="panel-grid">
          <article class="preview-frame">
            <div class="frame-heading">
              <span id="previewDesc"></span>
            </div>
            <div class="preview-body">
              <div class="shot-stage" id="shotStage">
                <div class="placeholder-art" id="placeholderArt">
                  <div><b id="phTitle"></b><p id="phText"></p></div>
                </div>
                <div class="comparison" id="comparison">
                  <div class="shot-off" id="shotOff"></div>
                  <div class="shot-on" id="shotOn"></div>
                  <div class="split-line"></div>
                  <div class="split-knob">&#8646;</div>
                  <div class="shot-labels"><span>Enabled</span><span>Disabled</span></div>
                  <input class="compare-range" id="compareRange" type="range"
                         min="0" max="100" value="50"
                         aria-label="Compare enabled and disabled screenshots" />
                </div>
                <div class="single-shot" id="singleShot" onclick="zoomSingle()"></div>
                <div class="gallery-thumbs" id="galleryThumbs" style="display:none;"></div>
              </div>
            </div>
          </article>

          <aside class="details-frame" id="filesDrawer">
            <div class="frame-heading">
              <span>Details</span>
              <span style="display:flex;align-items:center;gap:10px;">
                <span id="statusText"></span>
                <button class="drawer-close" onclick="toggleDrawer()">&#10006;</button>
              </span>
            </div>
            <div class="details-body">
              <div class="info-box"><h3>Effect</h3><p id="effectText"></p></div>
              <div class="info-box grow"><h3>Files (<span id="fileN"></span>)</h3>
                <div class="file-list d2scroll" id="fileList"></div></div>
            </div>
          </aside>
        </div>

      </div>
    </section>
  </section>
</main>
<div id="lightbox" onclick="this.style.display='none'"><img /></div>
<div id="toast"></div>
<div id="gameVer"></div>
<div id="modVer"></div>
<a id="ghLink" href="https://github.com/cristian1991/D2rEQmod"
   target="_blank"><svg viewBox="0 0 16 16" aria-hidden="true"><path d="M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38 0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13-.28-.15-.68-.52-.01-.53.63-.01 1.08.58 1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.51-1.07-1.78-.2-3.64-.89-3.64-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82.64-.18 1.32-.27 2-.27s1.36.09 2 .27c1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48 0 1.07-.01 1.93-.01 2.2 0 .21.15.46.55.38A8.01 8.01 0 0 0 16 8c0-4.42-3.58-8-8-8z"/></svg>GitHub &mdash; D2rEQmod</a>
<div id="cornerCtrls">
  <button class="ctrl" id="sndBtn" onclick="toggleSound()" title="Tristram theme">Sound</button>
  <button class="ctrl" id="bgBtn" onclick="toggleBg()" title="Background video">BG</button>
</div>
<audio id="bgmusic" loop preload="none" src="/music"></audio>

<script>
let DATA = null, selected = null, compareMode = "compare";

async function refresh(keep) {
  const r = await fetch("/api/features");
  DATA = await r.json();
  document.getElementById("gameVer").textContent = "game " + DATA.version;
  document.getElementById("modVer").textContent =
    "eq mod " + (DATA.mod_version || "");
  const w = document.getElementById("updWarn");
  if (DATA.updated) {
    w.style.display = "block";
    w.innerHTML = "D2R has updated (" + DATA.updated + " → " + DATA.version +
      "). Vanilla layouts or strings may have shifted under the mod." +
      '<button class="game-btn secondary" onclick="runDoctor()">Run Merge Doctor</button>';
  }
  const prev = keep && selected ? selected.name : null;
  selected = DATA.features.find(f => f.name === prev) || DATA.features[0];
  render();
}

function pillClass(s){return s==="ON"?"":(s==="OFF"?"off":"mixed");}
function pillText(s){return s;}

function render() {
  const list = document.getElementById("modList");
  list.innerHTML = DATA.features.map(f => `
    <button class="mod-tab ${f.name===selected.name?"active":""}" data-mod="${f.name}">
      <span class="rune ${f.state==="ON"?"":"off"}"><img src="/sprites/icon_${f.name}.png" alt="" onerror="this.remove()"></span>
      <span>${f.name.replace(/-/g," ")}</span>
      <span class="pill ${pillClass(f.state)}">${pillText(f.state)}</span>
    </button>`).join("");
  [...list.querySelectorAll(".mod-tab")].forEach(b =>
    b.addEventListener("click", () => {
      selected = DATA.features.find(f => f.name === b.dataset.mod);
      variantPick = null;
      compareMode = "compare"; render();
    }));

  const f = selected;
  document.getElementById("modTitle").textContent = f.name.replace(/-/g, " ");
  document.getElementById("previewDesc").textContent = f.desc;
  document.getElementById("effectText").textContent = f.desc;
  document.getElementById("statusText").textContent =
    (f.state === "ON" ? "Active" : (f.state === "OFF" ? "Dormant" : "Partial"))
    + " · " + f.files.length + " files · " + f.mb + " MB";

  const btn = document.getElementById("toggleBtn");
  btn.className = "game-btn" + (f.state === "ON" ? " enabled" : "") +
    (f.locked ? " locked" : "");
  btn.disabled = !!f.locked;
  btn.textContent = f.locked ? "Protected" :
    (f.state === "ON" ? (variantDirty(f) ? "Apply Mode" : "Enabled")
                      : "Disabled");

  const vs = document.getElementById("variantSel");
  if (f.variants && f.variants.length) {
    const v = f.variants[0];
    const pick = variantPick !== null ? variantPick
               : (v.state === "ON" ? "on" : "off");
    const mark = s => (v.state === s ? "\u2726 " : "\u2002\u2002 ");
    vs.style.display = "";
    vs.innerHTML =
      `<option value="off" ${pick==="off"?"selected":""}>${mark("OFF")}${v.off_label}</option>` +
      `<option value="on" ${pick==="on"?"selected":""}>${mark("ON")}${v.on_label}</option>`;
    vs.dataset.variant = v.name;
    vs.title = v.desc + " \u2726 = currently active mode.";
  } else { vs.style.display = "none"; vs.innerHTML = ""; }

  document.getElementById("fileN").textContent = f.files.length;
  document.getElementById("filesBtn").textContent =
    "Files (" + f.files.length + ")";
  document.getElementById("fileList").innerHTML = f.files.map(p => `
    <div class="file-row"><span>${p.path}</span>
      <span class="tag ${p.bk?"bk":""}">${p.bk?".bk":"live"}</span></div>`).join("");

  renderPreview(f);
}

let currentView = 0;

function preferredView(f) {
  // active variant mode picks its matching gallery view automatically
  if (f.variants && f.variants.length && f.views && f.views.length) {
    const v = f.variants[0];
    const mode = variantPick !== null ? variantPick
               : (v.state === "ON" ? "on" : "off");
    const want = mode === "on" ? v.view_on : v.view_off;
    if (want) {
      const i = f.views.findIndex(x => x.key === want);
      if (i >= 0) return i;
    }
  }
  return Math.min(currentView, (f.views ? f.views.length : 1) - 1);
}

function renderPreview(f, keepView) {
  const comp = document.getElementById("comparison");
  const single = document.getElementById("singleShot");
  const ph = document.getElementById("placeholderArt");
  const thumbs = document.getElementById("galleryThumbs");
  comp.classList.remove("show"); single.classList.remove("show");
  ph.style.display = "none"; thumbs.style.display = "none";
  thumbs.innerHTML = "";

  const views = f.views || [];
  if (!views.length) {
    ph.style.display = "grid";
    document.getElementById("phTitle").textContent = f.name.replace(/-/g, " ");
    document.getElementById("phText").textContent = f.desc +
      (f.name === "intro-videos" ? "" :
       " — add screenshots to see the change here.");
    return;
  }
  if (!keepView) currentView = preferredView(f);
  const v = views[currentView];
  if (v.on && v.off) {
    comp.classList.add("show");
    document.getElementById("shotOn").style.backgroundImage = "url('" + v.on + "')";
    document.getElementById("shotOff").style.backgroundImage = "url('" + v.off + "')";
    comp.style.setProperty("--split", "50%");
    document.getElementById("compareRange").value = 50;
  } else {
    const img = v.single || v.on || v.off;
    single.classList.add("show");
    single.style.backgroundImage = "url('" + img + "')";
  }
  if (views.length > 1) {
    thumbs.style.display = "flex";
    thumbs.innerHTML = views.map((x, i) => `
      <button class="gal-thumb ${i===currentView?"active":""}" data-i="${i}"
        style="background-image:url('${x.on||x.single||x.off}')">
        <span>${x.label}</span></button>`).join("");
    [...thumbs.querySelectorAll(".gal-thumb")].forEach(b =>
      b.addEventListener("click", () => {
        currentView = +b.dataset.i; renderPreview(f, true);
      }));
  }
}

let MOD_INSTALLED = false;
async function refreshInstall(){
  const r = await fetch("/api/modinstall");
  const d = await r.json();
  MOD_INSTALLED = d.installed;
  const b = document.getElementById("installBtn");
  b.textContent = d.installed ? "Uninstall Mod" : "Install Mod";
  if (d.bnet_running) {
    b.disabled = true;
    b.classList.add("locked");
    b.title = "Close Battle.net to " +
      (d.installed ? "uninstall" : "install") +
      " - it overwrites its settings on exit";
  } else {
    b.disabled = false;
    b.classList.remove("locked");
    b.title = "";
  }
}
setInterval(refreshInstall, 15000);
async function installMod(){
  const r = await fetch("/api/modinstall", {method:"POST",
    body: JSON.stringify({install: !MOD_INSTALLED})});
  toast(await r.text(), 7000);
  refreshInstall();
}
async function launchGame(){
  const r = await fetch("/api/launch", {method:"POST"});
  toast(await r.text(), 6000);
}
function toggleDrawer(){
  document.getElementById("filesDrawer").classList.toggle("open");
}
function zoomSingle(){
  const lb = document.getElementById("lightbox");
  lb.querySelector("img").src =
    document.getElementById("singleShot").style.backgroundImage.slice(5,-2);
  lb.style.display = "flex";
}
document.getElementById("compareRange").addEventListener("input", e =>
  document.getElementById("comparison").style.setProperty("--split", e.target.value + "%"));

function variantDirty(f) {
  const v = f.variants && f.variants[0];
  if (!v || variantPick === null) return false;
  return (v.state === "ON") !== (variantPick === "on");
}

async function toggleSelected() {
  const f = selected;
  if (f.state === "ON" && variantDirty(f)) {
    // option stays on; just switch it to the selected mode
    await applyVariantIfNeeded(f);
    toast("Mode changed — restart the game to apply.", 5000);
    variantPick = null;
    refresh(true);
    return;
  }
  const en = f.state !== "ON";
  if (en) await applyVariantIfNeeded(f);   // stage the chosen mode first
  const r = await fetch("/api/toggle", {method:"POST",
    body: JSON.stringify({feature: f.name, enable: en})});
  if (r.ok) {
    toast(f.name.replace(/-/g, " ") + (en ? " enabled" : " disabled")
      + " — restart the game to apply.", 5000);
  } else {
    toast("Something went wrong: " + await r.text(), 7000);
  }
  variantPick = null;
  refresh(true);
}
let variantPick = null;   // staged dropdown choice, applied on button press

function variantChanged(sel) {
  variantPick = sel.value;
  render();   // updates the main button label + previewed gallery view
}

async function applyVariantIfNeeded(f) {
  const v = f.variants && f.variants[0];
  if (!v || variantPick === null) return false;
  const want = variantPick === "on";
  if ((v.state === "ON") === want) return false;
  const r = await fetch("/api/toggle", {method:"POST",
    body: JSON.stringify({feature: v.name, enable: want})});
  return r.ok;
}
async function runDoctor() {
  toast("rescanning and running merge doctor...");
  const r = await fetch("/api/doctor", {method:"POST"});
  toast(await r.text(), 12000);
  refresh(true);
}
const music = () => document.getElementById("bgmusic");
function toggleSound(){
  const a = music(), b = document.getElementById("sndBtn");
  if (a.paused) { a.volume = 0.45; a.play(); b.classList.add("on");
    localStorage.setItem("eq_snd", "1"); }
  else { a.pause(); b.classList.remove("on");
    localStorage.setItem("eq_snd", "0"); }
}
function toggleBg(){
  const v = document.getElementById("bgvid"),
        b = document.getElementById("bgBtn");
  if (!v) return;
  if (v.style.display === "none") { v.style.display = ""; v.play();
    document.body.classList.remove("nobg");
    b.classList.add("on"); localStorage.setItem("eq_bg", "1"); }
  else { v.pause(); v.style.display = "none";
    document.body.classList.add("nobg"); b.classList.remove("on");
    localStorage.setItem("eq_bg", "0"); }
}
if (localStorage.getItem("eq_bg") === "0") {
  const v = document.getElementById("bgvid");
  if (v) { v.pause(); v.style.display = "none";
    document.body.classList.add("nobg"); }
} else document.getElementById("bgBtn").classList.add("on");
if (localStorage.getItem("eq_snd") === "1") {
  // browsers block autoplay with sound; resume on first interaction
  const tryPlay = () => { toggleSound();
    window.removeEventListener("pointerdown", tryPlay); };
  window.addEventListener("pointerdown", tryPlay);
}
let toastTimer = null;
function toast(msg, ms) {
  const t = document.getElementById("toast");
  t.textContent = msg; t.style.display = "block";
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => t.style.display = "none", ms || 5000);
}
// show only the burning background until everything is ready
Promise.all([
  refresh(),
  document.fonts ? document.fonts.ready : Promise.resolve(),
  refreshInstall(),
]).then(() => requestAnimationFrame(() => {
  document.querySelector(".app-shell").classList.add("ready");
  const v = document.getElementById("bgvid");
  if (v) v.classList.add("zoomed");
}));
</script>
</body>
</html>"""


def shot(feat, suffix):
    for ext in (".png", ".jpg", ".jpeg", ".webp"):
        p = os.path.join(SHOTS, feat + suffix + ext)
        if os.path.isfile(p):
            return "/shots/" + feat + suffix + ext
    return None


def gallery(feat):
    """Screenshot views for a feature.

    File naming in screenshots/:
      <feat>_on.png + <feat>_off.png          -> view 'overview' (slider)
      <feat>_<view>_on.png + ..._off.png      -> named view (slider)
      <feat>_<view>.png                       -> named view (single shot)
    """
    exts = (".png", ".jpg", ".jpeg", ".webp")
    groups = {}
    try:
        files = os.listdir(SHOTS)
    except OSError:
        files = []
    for fn in files:
        stem, ext = os.path.splitext(fn)
        if ext.lower() not in exts or not stem.startswith(feat + "_"):
            continue
        rest = stem[len(feat) + 1:]
        if rest in ("on", "off"):
            view, kind = "overview", rest
        elif rest.endswith("_on") or rest.endswith("_off"):
            view, kind = rest.rsplit("_", 1)
        else:
            view, kind = rest, "single"
        groups.setdefault(view, {})[kind] = "/shots/" + fn
    out = []
    for view in sorted(groups, key=lambda v: (v != "overview", v)):
        g = groups[view]
        out.append({"label": view.replace("-", " "),
                    "key": view,
                    "on": g.get("on"), "off": g.get("off"),
                    "single": g.get("single")})
    return out


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, body, ctype="application/json", code=200):
        data = body if isinstance(body, bytes) else body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.path == "/":
            return self._send(PAGE, "text/html; charset=utf-8")
        if self.path.startswith("/sprites/"):
            p = os.path.join(HERE, "sprites", os.path.basename(self.path))
            if os.path.isfile(p) and p.endswith(".png"):
                with open(p, "rb") as f:
                    return self._send(f.read(), "image/png")
            return self._send("not found", "text/plain", 404)
        if self.path == "/music":
            p = os.path.join(HERE, "tristram.flac")
            if os.path.isfile(p):
                with open(p, "rb") as f:
                    return self._send(f.read(), "audio/flac")
            return self._send("not found", "text/plain", 404)
        if self.path == "/bg.webm":
            p = os.path.join(HERE, "logoloop.webm")
            if not os.path.isfile(p):
                try:
                    import casc
                    if casc.available():
                        st = casc.Storage()
                        st.extract(
                            b"data:data/hd/global/video/logoloop.webm", p)
                        st.close()
                except Exception:
                    pass
            if os.path.isfile(p):
                with open(p, "rb") as f:
                    return self._send(f.read(), "video/webm")
            return self._send("not found", "text/plain", 404)
        if self.path == "/favicon.ico":
            p = os.path.join(HERE, "favicon.ico")
            if os.path.isfile(p):
                with open(p, "rb") as f:
                    return self._send(f.read(), "image/x-icon")
            return self._send("", "text/plain", 404)
        if self.path.startswith("/fonts/"):
            key = os.path.basename(self.path)
            for p in FONTS.get(key, []):
                if os.path.isfile(p):
                    with open(p, "rb") as f:
                        return self._send(f.read(), "font/woff")
            return self._send("not found", "text/plain", 404)
        if self.path.startswith("/shots/"):
            p = os.path.join(SHOTS, os.path.basename(self.path))
            if os.path.isfile(p):
                ctype = mimetypes.guess_type(p)[0] or "image/png"
                with open(p, "rb") as f:
                    return self._send(f.read(), ctype)
            return self._send("not found", "text/plain", 404)
        if self.path == "/api/modinstall":
            mode, installed = mod_install_state()
            return self._send(json.dumps(
                {"mode": mode, "installed": installed,
                 "bnet_running": mode == "bnet" and bnet_running()}))
        if self.path == "/api/features":
            data = eqtool.rescan()
            st = eqtool.load_state()
            ver = eqtool.game_version()
            updated = (st.get("game_version")
                       if st.get("game_version")
                       and st["game_version"] != ver else None)
            st["game_version"] = ver
            eqtool.save_state(st)
            feats = []
            for name in sorted(data["features"]):
                # core is protected; "strings" is superseded by the
                # key-level patch options below
                # fonts = the icon-glyph OTF; it is part of item-icons
                if name in ("core-modinfo", "strings", "fonts"):
                    continue
                if name in _HIDDEN or name in _NEVER_RENAME:
                    continue
                rows = data["features"][name]
                feats.append({
                    "name": name,
                    "icon": ICONS.get(name, ""),
                    "state": eqtool.feature_state(rows),
                    "mb": round(sum(r["size"] for r in rows) / 1e6, 1),
                    "shared": any(r["toggle"] == "shared" for r in rows),
                    "locked": any(r["toggle"] == "never" for r in rows),
                    "desc": DESCRIPTIONS.get(name, ""),
                    "shot_on": shot(name, "_on"),
                    "shot_off": shot(name, "_off"),
                    "views": gallery(name),
                    "files": [{"path": r["path"], "bk": r["disabled"]}
                              for r in rows],
                })
            for gname, spec in patches.GROUPS.items():
                if gname in _HIDDEN:
                    continue
                try:
                    gstate = patches.state(gname)
                    gfiles = patches.files_info(gname)
                except Exception:
                    continue
                if gname == "item-icons-and-nameplates":
                    gfiles += [{"path": r["path"], "bk": r["disabled"]}
                               for r in data["features"].get("fonts", [])]
                feats.append({
                    "name": gname,
                    "icon": ICONS.get(gname, ""),
                    "state": gstate,
                    "mb": 0.0,
                    "shared": False,
                    "patch": True,
                    "locked": False,
                    "desc": DESCRIPTIONS.get(gname, spec["desc"]),
                    "shot_on": shot(gname, "_on"),
                    "shot_off": shot(gname, "_off"),
                    "views": gallery(gname),
                    "files": gfiles,
                })
            for vname, vspec in VARIANTS.items():
                if "parent" in vspec:
                    continue        # attached to the parent card below
                feats.append({
                    "name": vname, "icon": ICONS.get(vname, ""),
                    "state": variant_state(vname), "mb": 0.0,
                    "shared": False, "patch": True, "locked": False,
                    "desc": vspec["desc"],
                    "shot_on": shot(vname, "_on"),
                    "shot_off": shot(vname, "_off"),
                    "views": gallery(vname),
                    "files": [{"path": vspec.get(
                        "label", "(variant swap)"), "bk": False}],
                })
            for cname, spec in COMPOSITES.items():
                states, cfiles, mb = [], [], 0.0
                for m in spec["renames"]:
                    rows = data["features"].get(m, [])
                    states.append(eqtool.feature_state(rows))
                    mb += sum(r["size"] for r in rows) / 1e6
                    cfiles += [{"path": r["path"], "bk": r["disabled"]}
                               for r in rows]
                for m in spec["patches"]:
                    try:
                        states.append(patches.state(m))
                        cfiles += patches.files_info(m)
                    except Exception:
                        pass
                for m in spec.get("layouts", []):
                    try:
                        states.append(layouts.state(m))
                        cfiles += layouts.files_info(m)
                    except Exception:
                        pass
                cstate = ("ON" if all(s == "ON" for s in states)
                          else "OFF" if all(s == "OFF" for s in states)
                          else "MIXED")
                feats.append({
                    "name": cname, "icon": ICONS.get(cname, ""),
                    "state": cstate, "mb": round(mb, 1),
                    "shared": False, "patch": False, "locked": False,
                    "desc": DESCRIPTIONS.get(cname, ""),
                    "shot_on": shot(cname, "_on"),
                    "shot_off": shot(cname, "_off"),
                    "views": gallery(cname),
                    "files": cfiles,
                })
            # nest parented variants inside their parent option card
            for vname, vspec in VARIANTS.items():
                parent = vspec.get("parent")
                if not parent:
                    continue
                pf = next((f for f in feats if f["name"] == parent), None)
                if pf is None:
                    continue
                pf.setdefault("variants", []).append({
                    "name": vname,
                    "title": vspec.get("title", vname.replace("-", " ")),
                    "state": variant_state(vname),
                    "desc": vspec["desc"],
                    "on_label": vspec.get("on_label", "On"),
                    "off_label": vspec.get("off_label", "Off"),
                    "view_on": vspec.get("view_on"),
                    "view_off": vspec.get("view_off"),
                })
            feats.sort(key=lambda f: f["name"])
            return self._send(json.dumps({
                "version": ver, "updated": updated,
                "mod_version": MOD_VERSION,
                "count": sum(len(v) for v in data["features"].values()),
                "features": feats}))
        return self._send("not found", "text/plain", 404)

    def do_POST(self):
        n = int(self.headers.get("Content-Length") or 0)
        body = json.loads(self.rfile.read(n) or b"{}") if n else {}
        if self.path == "/api/toggle":
            feat = body.get("feature")
            if feat in VARIANTS:
                variant_set(feat, bool(body.get("enable")))
                eqtool.journal("variant {} -> {}".format(
                    feat, "on" if body.get("enable") else "off"))
                return self._send("{} {}".format(
                    "enabled" if body.get("enable") else "disabled",
                    feat), "text/plain")
            if feat in COMPOSITES:
                en = bool(body.get("enable"))
                spec = COMPOSITES[feat]
                import io
                import contextlib
                data = eqtool.rescan()
                nfiles = 0
                for m in spec["renames"]:
                    if m in data["features"]:
                        with contextlib.redirect_stdout(io.StringIO()):
                            eqtool.set_feature(data, m, en, apply=True)
                        nfiles += len(data["features"][m])
                nkeys = 0
                for m in spec["patches"]:
                    nkeys += patches.set_group(m, en)
                for m in spec.get("layouts", []):
                    nkeys += layouts.set_group(m, en)
                eqtool.journal("composite {} {} ({} files, {} keys)".format(
                    "enable" if en else "disable", feat, nfiles, nkeys))
                return self._send("{} {}".format(
                    "enabled" if en else "disabled", feat), "text/plain")
            if feat in patches.GROUPS:
                en = bool(body.get("enable"))
                n = patches.set_group(feat, en)
                extra = ""
                if feat == "item-icons-and-nameplates":
                    # the icon glyphs live in the modded font: keep the
                    # OTF override in lockstep with the string edits
                    import io
                    import contextlib
                    data = eqtool.rescan()
                    if "fonts" in data["features"]:
                        with contextlib.redirect_stdout(io.StringIO()):
                            eqtool.set_feature(data, "fonts", en,
                                               apply=True)
                        extra = " + icon font"
                eqtool.journal("patch {} {} ({} keys{})".format(
                    "enable" if en else "disable", feat, n, extra))
                return self._send(
                    "{} {} ({} keys{})".format(
                        "enabled" if en else "disabled",
                        feat, n, extra), "text/plain")
            data = eqtool.rescan()
            if feat not in data["features"]:
                return self._send("unknown feature", "text/plain", 400)
            import io
            import contextlib
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                eqtool.set_feature(data, feat, bool(body.get("enable")),
                                   apply=True)
            return self._send(buf.getvalue(), "text/plain")
        if self.path == "/api/modinstall":
            try:
                msg = mod_install(bool(body.get("install")))
                return self._send(msg, "text/plain")
            except Exception as e:
                return self._send("failed: {}".format(e),
                                  "text/plain", 500)
        if self.path == "/api/launch":
            try:
                bnet = None
                for p in (r"C:\Program Files (x86)\Battle.net"
                          r"\Battle.net.exe",
                          r"C:\Program Files\Battle.net"
                          r"\Battle.net.exe"):
                    if os.path.isfile(p):
                        bnet = p
                        break
                if bnet:
                    # make sure the launch args are installed, then let
                    # Battle.net launch with the user's session/region
                    mode, installed = mod_install_state()
                    if mode == "bnet" and not installed:
                        mod_install(True)
                    subprocess.Popen([bnet, "--exec=launch OSI"])
                    return self._send(
                        "Launching D2R through Battle.net "
                        "(mod args from launcher settings)...",
                        "text/plain")
                game_dir = os.path.dirname(eqtool.GAME_EXE)
                subprocess.Popen(
                    [eqtool.GAME_EXE, "-mod", "eq", "-txt"],
                    cwd=game_dir)
                return self._send(
                    "D2R launching directly with -mod eq -txt ...",
                    "text/plain")
            except Exception as e:
                return self._send("launch failed: {}".format(e),
                                  "text/plain", 500)
        if self.path == "/api/doctor":
            r = subprocess.run(
                [sys.executable, os.path.join(HERE, "doctor.py"),
                 "--install"],
                capture_output=True, text=True,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            return self._send(r.stdout + r.stderr, "text/plain")
        return self._send("not found", "text/plain", 404)


def ensure_assets():
    """First-run: pull heavy media from the user's own game install
    (nothing Blizzard-derived ships with the tool download)."""
    try:
        import casc
        if not casc.available():
            return
        st = None
        jobs = [
            ("logoloop.webm",
             bytes(r"data:data\hd\global\video\logoloop.webm", "ascii")),
            ("tristram.flac",
             bytes(r"data:data\global\music\act1\tristram.flac", "ascii")),
        ]
        for fn, name in jobs:
            p = os.path.join(HERE, fn)
            if not os.path.isfile(p):
                st = st or casc.Storage()
                st.extract(name, p)
        if st:
            st.close()
    except Exception:
        pass
    # favicon from the user's own D2R.exe
    fav = os.path.join(HERE, "favicon.ico")
    if not os.path.isfile(fav) and eqtool.GAME_EXE:
        ps = ("Add-Type -AssemblyName System.Drawing;"
              "$i=[System.Drawing.Icon]::ExtractAssociatedIcon('{exe}');"
              "$fs=[System.IO.File]::Create('{fav}');$i.Save($fs);"
              "$fs.Close()").format(exe=eqtool.GAME_EXE, fav=fav)
        try:
            subprocess.run(["powershell", "-NoProfile", "-Command", ps],
                           capture_output=True, timeout=30,
                           creationflags=getattr(subprocess,
                                                 "CREATE_NO_WINDOW", 0))
        except Exception:
            pass
    # vanilla baseline for the update doctor
    if not os.path.isdir(os.path.join(HERE, "baselines")) or not any(
            d.startswith("vanilla_") for d in
            os.listdir(os.path.join(HERE, "baselines"))):
        try:
            subprocess.Popen([sys.executable,
                              os.path.join(HERE, "extract_casc.py")],
                             creationflags=getattr(subprocess,
                                                   "CREATE_NO_WINDOW", 0))
        except Exception:
            pass


def main():
    os.makedirs(SHOTS, exist_ok=True)
    ensure_assets()
    srv = ThreadingHTTPServer(("127.0.0.1", PORT), H)
    url = "http://127.0.0.1:{}".format(PORT)

    def open_ui():
        # Edge app mode = chromeless native-feeling window; fall back
        # to the default browser tab. App windows ignore
        # --start-maximized, so size the window to the work area.
        try:
            import ctypes
            import ctypes.wintypes
            rect = ctypes.wintypes.RECT()
            ctypes.windll.user32.SystemParametersInfoW(
                0x0030, 0, ctypes.byref(rect), 0)   # SPI_GETWORKAREA
            w = rect.right - rect.left
            h = rect.bottom - rect.top
            pos = (rect.left, rect.top)
        except Exception:
            w, h, pos = 1600, 900, (0, 0)
        for edge in (
            r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
            r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
        ):
            if os.path.isfile(edge):
                subprocess.Popen([
                    edge, "--app=" + url,
                    "--window-position=%d,%d" % pos,
                    "--window-size=%d,%d" % (w, h)])
                return
        webbrowser.open(url)

    threading.Timer(0.4, open_ui).start()
    print("eqtool GUI at {} (Ctrl+C to stop)".format(url))
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
