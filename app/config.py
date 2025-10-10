import configparser, os, sys
from pathlib import Path

def _bundle_root():
    # When frozen, files live in a temp folder at sys._MEIPASS; executable in sys.executable
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parents[1]

def load_config():
    root = _bundle_root()
    cfg = configparser.ConfigParser(interpolation=configparser.ExtendedInterpolation())
    # Look beside the EXE first (user-provided overrides), then fall back to bundled example
    paths = [str(root / "config.example.ini"), str(root / "config.ini")]
    cfg.read(paths)
    expand = os.path.expandvars
    return {
        "DB_PATH": expand(cfg["paths"]["db_path"]),
        "IMAGE_ROOT": expand(cfg["paths"]["image_root"]),
        "CACHE_DIR": expand(cfg["paths"]["cache_dir"]),
        "STANDARD_VERSION": cfg["app"].get("standard_version", "v1.0"),
        "BATCH_SIZE": cfg["app"].getint("batch_size", 20),
    }
