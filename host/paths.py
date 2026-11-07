"""External paths used by the c5maps host. Every value can be overridden with an env var.

  C5MAPS_CIV5      Civ 5 install folder      (default: Steam location)
  C5MAPS_MYGAMES   "My Games\\Sid Meier's Civilization 5"
  C5MAPS_MODS      MODS folder               (default: <MYGAMES>\\MODS)
  C5MAPS_DB        Civ5DebugDatabase.db      (default: <MYGAMES>\\cache\\Civ5DebugDatabase.db)
  C5MAPS_LOC_DB    Localization-Merged.db    (default: <MYGAMES>\\cache\\Localization-Merged.db)
"""
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ENGINE = os.path.join(ROOT, "engine")
DATA = os.path.join(ENGINE, "data")
RENDER = os.path.join(ROOT, "render")
OUT = os.path.join(ROOT, "out")

CIV5 = os.environ.get(
    "C5MAPS_CIV5",
    r"C:\Program Files (x86)\Steam\steamapps\common\Sid Meier's Civilization V")
MYGAMES = os.environ.get(
    "C5MAPS_MYGAMES",
    os.path.join(os.path.expanduser("~"), "Documents", "My Games", "Sid Meier's Civilization 5"))
MODS = os.environ.get("C5MAPS_MODS", os.path.join(MYGAMES, "MODS"))
DB = os.environ.get("C5MAPS_DB", os.path.join(MYGAMES, "cache", "Civ5DebugDatabase.db"))
LOC_DB = os.environ.get("C5MAPS_LOC_DB", os.path.join(MYGAMES, "cache", "Localization-Merged.db"))

CP_DIR = os.path.join(MODS, "(1) Community Patch")
VP_DIR = os.path.join(MODS, "(2) Vox Populi")

# Lua include search path, in VFS priority order (later wins).
LUA_DIRS = [
    os.path.join(CIV5, "Assets", "Gameplay", "Lua"),
    os.path.join(CIV5, "Assets", "DLC", "Expansion", "Gameplay", "Lua"),
    os.path.join(CIV5, "Assets", "DLC", "Expansion2", "Gameplay", "Lua"),
]
MOD_DIRS = [CP_DIR, VP_DIR]   # recursive; files listed with import="1" in the .modinfo when found

# Map script folders searched by bare name, in this order (first match wins).
# Each entry: (source tag, folder)
SCRIPT_DIRS = [
    ("mygames", os.path.join(MYGAMES, "Maps")),
    ("assets", os.path.join(CIV5, "Assets", "Maps")),
    ("exp1", os.path.join(CIV5, "Assets", "DLC", "Expansion", "Maps")),
    ("exp2", os.path.join(CIV5, "Assets", "DLC", "Expansion2", "Maps")),
    ("vp", os.path.join(VP_DIR, "Mapscripts")),
    ("vp-emp", os.path.join(VP_DIR, "Mapscripts", "EMP")),
    ("cp", os.path.join(CP_DIR, "Mapscripts")),
    ("dlc-sp1", os.path.join(CIV5, "Assets", "DLC", "DLC_SP_Maps", "Maps")),
    ("dlc-sp2", os.path.join(CIV5, "Assets", "DLC", "DLC_SP_Maps_2", "Maps")),
    ("dlc-sp3", os.path.join(CIV5, "Assets", "DLC", "DLC_SP_Maps_3", "Maps")),
]
