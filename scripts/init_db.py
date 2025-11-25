"""Database initialization and ingestion for the Image Review Tool.

This script scans the configured image root, filters filenames by a strict
pattern, inserts image metadata into the database, and seeds the review queue.
A configurable fraction of images are flagged for QC review (duplicate
review by a second user) and receive a second review row to enable inter-rater consistency checks.

Usage:
    python -m init_db
or:
    python init_db.py

Behavior:
  * Reads paths and parameters from `config.ini` via `app.config.load_config()`.
  * Ensures the schema exists and applies any migrations.
  * Walks all subfolders under `IMAGE_ROOT`.
  * Accepts only *.jpg / *.jpeg files whose names match `(\\d{11})_(000|001).jpg`.
  * Inserts each unique image into `images` with a SHA-256 digest.
  * Logs the device_id suffix (e.g. '000' or '001') as the variant
  * Flags ~QC_RATE of images as QC duplicates and seeds two review rows.
  * Seeds exactly one review row for non-QC images.
  * Re-running is idempotent: existing images/reviews are not duplicated.

Design notes:
  * The SHA-256 is used for integrity/duplicate detection and auditing.
  * The filename regex extracts an 11-digit device_id for later reporting.
  * All timestamps are UTC (`datetime('now')` in SQLite).
"""

import hashlib, os, sqlite3, random
from pathlib import Path
from app.config import load_config
from app.db import connect, ensure_schema, run_migrations
import re

IMG_EXT = {".jpg", ".jpeg"}

pattern = re.compile(r"^(\d{11})_(000|001)\.jpe?g$", re.IGNORECASE)


def sha256_file(path: str, block=1024 * 1024) -> str:
    """Compute the SHA-256 content hash of a file.

    Reads the file in fixed-size blocks to avoid excessive memory use.

    Args:
        path: Absolute or relative filesystem path to the file.
        block: Read size in bytes for each chunk (defaults to 1 MiB).

    Returns:
        Hex-encoded SHA-256 digest string of the file contents.

    Raises:
        OSError: If the file cannot be opened/read.
    """
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            b = f.read(block)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def main():
    """Scan the image root and seed the database with images and review rows.

    Steps:
      1) Load configuration (paths, QC rate, random seed).
      2) Connect to SQLite, ensure schema, and run migrations.
      3) Recursively walk the image root and filter acceptable files.
      4) For each matching file:
         - Insert into `images` if not present (path, device_id, variant, sha256, timestamp).
         - Randomly flag as QC with probability QC_RATE.
         - Seed one `reviews` row (status='unassigned').
         - If QC, seed a second independent `reviews` row (still 'unassigned'),
           but guard against >2 rows on re-runs.

    Logging:
      Prints counts of added and skipped files for quick operator feedback.

    Idempotency:
      Uses `INSERT OR IGNORE` and a defensive LIMIT to prevent duplication if
      re-run against the same dataset.

    Raises:
      RuntimeError: If the database cannot be opened.
      sqlite3.Error: On unexpected SQL errors.
      OSError: If files cannot be read for hashing.
    """
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
            variant = m.group(2) # "000" or "001"
            full = os.path.join(dirpath, name)

            try:
                digest = sha256_file(full)

                existing = con.execute(
                    "SELECT path FROM images WHERE sha256=?",
                    (digest,)
                ).fetchone()

                if existing:
                    print(f"[skip duplicate] {full} (same content as {existing[0]})")
                    skipped +=1
                    continue

                with con:
                    # register image
                    con.execute(
                        """
                        INSERT OR IGNORE INTO images(path, device_id, variant, sha256, registered_at)
                        VALUES (?,?,?,?, datetime('now'));
                        """,
                        (full, device_id, variant, digest),
                    )

                    # QC flag only for _000
                    qc_flag = 0
                    if variant == "000":
                        qc_rate = cfg["QC_RATE"]
                        qc_flag = 1 if random.random() < qc_rate else 0
                        con.execute("UPDATE images SET qc_flag=? WHERE path=?", (qc_flag, full))

                    # seed exactly one review row for every image (both 000 and 001)
                    con.execute(
                        """
                        INSERT OR IGNORE INTO reviews(image_id, status)
                        SELECT image_id, 'unassigned' FROM images WHERE path=?;
                        """,
                        (full,),
                    )

                    # if QC _000, add the second row
                    if qc_flag:
                        con.execute(
                            """
                            INSERT INTO reviews(image_id, status)
                            SELECT image_id, 'unassigned' FROM images WHERE path=?
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
