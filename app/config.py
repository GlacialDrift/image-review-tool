"""Configuration loader for the Image Review Tool.

This module centralizes all configuration parsing logic. It reads one or more
`.ini` files (typically `config.ini` or `config.example.ini`) and converts them
into a structured Python dictionary used by the rest of the application.

Key capabilities:
  * Handles both frozen (PyInstaller) and development environments.
  * Supports environment-variable expansion in path strings.
  * Allows for dynamic definition of results, key bindings, image display
    parameters, mouse behaviors, QC rates, and other app-level settings.
  * Provides backward compatibility for older `[keybinds]` sections if
    `[results]` is not defined.

Usage:
    from app.config import load_config
    cfg = load_config()
    db_path = cfg["DB_PATH"]

Returned configuration is a nested dictionary suitable for use throughout the
application.
"""

import configparser, os, sys
from pathlib import Path

def _split_list(s: str):
    """Split a comma-separated string into a list of stripped non-empty values."""
    return [k.strip() for k in s.split(",") if k.strip()]

def _bundle_root() -> Path:
    """Return the root path containing configuration and schema files.

    Detects whether the application is running as a frozen PyInstaller bundle or
    as a normal Python module.

    Returns:
        Path: The root directory where bundled resources reside.
    """
    return (
        Path(sys.executable).parent
        if getattr(sys, "frozen", False)
        else Path(__file__).resolve().parents[1]
    )

def _getint(section, key, cfg):
    """Safely extract an integer value from a config section.

    Args:
        section: Section name in the ConfigParser.
        key: Option key name within that section.
        cfg: ConfigParser object.

    Returns:
        int or None: The integer value if present and valid; otherwise None.
    """
    try:
        return cfg[section].getint(key)
    except Exception:
        return None

def _split_keys(cfg, section, option, default):
    """Split a comma-separated key list from configuration.

    Args:
        cfg: ConfigParser object.
        section: Section name in the INI file.
        option: Key name within the section.
        default: Default list of keys if not defined.

    Returns:
        list[str]: Parsed list of key symbols or the provided default.
    """
    if section in cfg and option in cfg[section]:
        return [k.strip() for k in cfg[section][option].split(",") if k.strip()]
    return default

def load_config():
    """Load and normalize configuration values from the INI files.

    Search order:
      1. `<bundle_root>/config.example.ini`
      2. `<bundle_root>/config.ini`

    The second file overrides the first if both exist.

    Sections handled:
      [paths]    — db_path, image_root, cache_dir
      [results]  — mapping of result labels to keys (preferred modern form)
      [keybinds] — legacy yes/no bindings (fallback)
      [image]    — display crop and alignment options
      [review]   — QC rate, random seed, etc.
      [app]      — version and batch size
      [mouse]    — left/right click behavior

    Returns:
        dict: Normalized configuration object containing:
            {
              "DB_PATH": str,
              "IMAGE_ROOT": str,
              "CACHE_DIR": str,
              "STANDARD_VERSION": str,
              "BATCH_SIZE": int,
              "QC_RATE": float,
              "KEYBINDS": {"yes": [...], "no": [...]},
              "RANDOM_SEED": int,
              "IMAGE": dict,
              "RESULT_BINDINGS": dict[str, list[str]],
              "MOUSE": dict[str, {"action": str|None, "point": bool}],
            }

    Raises:
        RuntimeError: If no `[paths]` section is found.
        ValueError: If the QC rate is outside [0.0, 1.0].
    """
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

    # Parse dynamic result bindings
    result_bindings = {}
    if "results" in cfg:
        for result_name, keys in cfg["results"].items():
            result_bindings[result_name.strip()] = _split_list(keys)

    # Back-compat fallback if [results] is not defined
    if not result_bindings:
        yes_keys = _split_keys(cfg, "keybinds", "yes", ["y", "b", "s"])
        no_keys = _split_keys(cfg, "keybinds", "no", ["n", "g"])
        result_bindings = {"yes": yes_keys, "no": no_keys}

    image = {}
    if "image" in cfg:
        image = {
            "crop_width": _getint("image", "crop_width", cfg),
            "crop_height": _getint("image","crop_height", cfg),
            "h_align": cfg["image"].get("h_align", "center").lower(),
            "v_align": cfg["image"].get("v_align", "center").lower(),
            "max_display_side": cfg["image"].getint("max_display_side", 1400),
        }

    yes_keys = _split_keys(cfg, "keybinds", "yes", ["y","b","s"])
    no_keys = _split_keys(cfg, "keybinds", "no", ["n","g"])
    rs = cfg["review"].getint("random_seed", 42)

    qc_rate = float(cfg["review"].get("qc_rate","0.10")) if "review" in cfg else 0.10
    if qc_rate < 0.0 or qc_rate > 1.0:
        raise ValueError("QC rate must be between 0.0 and 1.0")

    mouse = {"left": {"action": None, "point": False},
             "right": {"action": None, "point": False}}
    if "mouse" in cfg:
        for btn in ("left", "right"):
            if btn in cfg["mouse"]:
                tokens = [t.strip().lower() for t in cfg["mouse"][btn].split(",") if t.strip()]
                # 'point' is a flag, anything else we treat as the result label
                action = next((t for t in tokens if t != "point"), None)
                point = "point" in tokens
                mouse[btn] = {"action": action, "point": point}

    return {
        "DB_PATH": expand(cfg["paths"]["db_path"]),
        "IMAGE_ROOT": expand(cfg["paths"]["image_root"]),
        "CACHE_DIR": expand(cfg["paths"]["cache_dir"]),
        "STANDARD_VERSION": cfg["app"].get("standard_version", "v1.0"),
        "BATCH_SIZE": cfg["app"].getint("batch_size", 20),
        "QC_RATE": qc_rate,
        "KEYBINDS": {"yes": yes_keys, "no": no_keys},
        "RANDOM_SEED": rs,
        "IMAGE": image,
        "RESULT_BINDINGS": result_bindings,
        "MOUSE": mouse,
    }
