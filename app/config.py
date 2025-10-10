import configparser, os
from pathlib import Path

def load_config():
    root = Path(__file__).resolve().parents[1]
    cfg = configparser.ConfigParser(interpolation=configparser.ExtendedInterpolation())
    cfg.read([str(root / "config.example.ini"), str(root / "config.ini")])
    expand = os.path.expandvars
    return {
        "DB_PATH": expand(cfg["paths"]["db_path"]),
        "IMAGE_ROOT": expand(cfg["paths"]["image_root"]),
        "CACHE_DIR": expand(cfg["paths"]["cache_dir"]),
        "STANDARD_VERSION": cfg["app"].get("standard_version", "v1.0"),
        "BATCH_SIZE": cfg["app"].getint("batch_size", 20),
    }
