import hashlib, os, sqlite3
from pathlib import Path
from app.config import load_config
from app.db import connect, ensure_schema
import re

IMG_EXT = {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp"}

pattern = re.compile(r"^(\d{11})_000\.jpe?g$", re.IGNORECASE)

def sha256_file(path: str, block=1024*1024) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            b = f.read(block)
            if not b: break
            h.update(b)
    return h.hexdigest()

def main():
    cfg = load_config()
    con = connect(cfg["DB_PATH"])
    ensure_schema(con, str(Path(__file__).resolve().parents[1] / "schema.sql"))

    root = cfg["IMAGE_ROOT"]
    added = 0
    skipped = 0

    print(f"Scanning all subfolders of: {root}")
    for dirpath, _, files in os.walk(root):
        for name in files:
            ext = os.path.splitext(name)[1].lower()
            if ext not in IMG_EXT:
                continue

            m = pattern.match(name)
            if not m:
                skipped += 1
                # Skip all non-_000 images or wrong names
                continue

            device_id = m.group(1)
            full = os.path.join(dirpath, name)

            try:
                digest = sha256_file(full)
                with con:
                    con.execute("""
                        INSERT OR IGNORE INTO images(path, device_id, sha256, registered_at)
                        VALUES (?,?,?, datetime('now'));
                    """, (full, device_id, digest))
                    con.execute("""
                        INSERT OR IGNORE INTO reviews(image_id, status)
                        SELECT image_id, 'unassigned' FROM images WHERE path=?;
                    """, (full,))
                added += 1
            except Exception as e:
                print(f"[skip] {full}: {e}")

    print(f"Added {added} qualifying images.")
    print(f"Skipped {skipped} non-_000 files.")

if __name__ == "__main__":
    main()
