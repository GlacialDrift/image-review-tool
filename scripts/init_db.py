import hashlib, os, sqlite3, random
from pathlib import Path
from app.config import load_config
from app.db import connect, ensure_schema, run_migrations
import re

IMG_EXT = {".jpg", ".jpeg"}

pattern = re.compile(r"^(\d{11})_000\.jpe?g$", re.IGNORECASE)


def sha256_file(path: str, block=1024 * 1024) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            b = f.read(block)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def main():
    cfg = load_config()
    qc_rate = cfg["QC_RATE"]
    random.seed(cfg.get("RANDOM_SEED"))

    con = connect(cfg["DB_PATH"])
    ensure_schema(con, str(Path(__file__).resolve().parents[1] / "schema.sql"))
    run_migrations(con)

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
                    # existing insert
                    con.execute(
                        """
                        INSERT OR IGNORE INTO images(path, device_id, sha256, registered_at)
                        VALUES (?,?,?, datetime('now'));
                    """,
                        (full, device_id, digest),
                    )

                    # mark ~10% as QC
                    qc_flag = 1 if random.random() < qc_rate else 0
                    con.execute(
                        "UPDATE images SET qc_flag=? WHERE path=?", (qc_flag, full)
                    )

                    # seed review rows
                    con.execute(
                        """
                        INSERT OR IGNORE INTO reviews(image_id, status)
                        SELECT image_id, 'unassigned' FROM images WHERE path=?;
                    """,
                        (full,),
                    )

                    if qc_flag:
                        # add a second independent row for QC images
                        con.execute(
                            """
                            INSERT INTO reviews(image_id, status)
                            SELECT image_id, 'unassigned' FROM images WHERE path=?
                            -- defensively avoid creating >2 rows if re-run
                            AND (SELECT COUNT(*) FROM reviews r WHERE r.image_id = images.image_id) < 2;
                        """,
                            (full,),
                        )

                added += 1
            except Exception as e:
                print(f"[skip] {full}: {e}")

    print(f"Added {added} qualifying images.")
    print(f"Skipped {skipped} non-_000 files.")


if __name__ == "__main__":
    main()
