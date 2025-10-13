# app/config.py
import configparser, os, sys
from pathlib import Path

def _bundle_root() -> Path:
    # When frozen by PyInstaller, the executable lives in a folder we control
    return Path(sys.executable).parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parents[1]

def load_config():
    root = _bundle_root()
    cfg = configparser.ConfigParser(interpolation=configparser.ExtendedInterpolation())

    # Look beside the EXE first
    files = [root / "config.example.ini", root / "config.ini"]
    cfg.read([str(p) for p in files if p.exists()])

    if "paths" not in cfg:
        raise RuntimeError(
            "Missing config: Place a 'config.ini' next to the executable (you can copy 'config.example.ini')."
        )

    expand = os.path.expandvars
    return {
        "DB_PATH": expand(cfg["paths"]["db_path"]),
        "IMAGE_ROOT": expand(cfg["paths"]["image_root"]),
        "CACHE_DIR": expand(cfg["paths"]["cache_dir"]),
        "STANDARD_VERSION": cfg["app"].get("standard_version", "v1.0"),
        "BATCH_SIZE": cfg["app"].getint("batch_size", 20),
    }
