"""
Reset reviews (and their annotations) for all images that share device IDs with a provided list of images.

Goal: "as if never reviewed" — i.e., clear decisions and assignment metadata and remove any annotations for those reviews.

What it does:
- Reads a CSV of targets. The CSV can contain one of the following columns:
  - image_id
  - path (relative or absolute path stored in the DB's images.path)
  - filename (basename; resolves all matches)
  - device_id (optional; if present, it's used directly)
- Loads DB path from your existing config (config.py/config.ini).
- Finds all device_ids for the listed images, then finds *all* reviews for *all* images with those device_ids.
- Deletes annotations for those review_ids and resets the review rows:
    status='unassigned', result=NULL, assigned_to=NULL, decided_at=NULL, batch_id=NULL, standard_version=NULL
- Provides --dry-run to preview changes.

Usage:
    python reset_reviews_by_device.py \
        --csv /path/to/targets.csv \
        --confirm                          # actually execute

    # Preview only
    python reset_reviews_by_device.py --csv targets.csv --dry-run

CSV examples:
    image_id\n12345\n67890

    path\nsubdir/12345678901_000.jpg\nsubdir/12345678901_001.jpg

    filename\n12345678901_000.jpg\n12345678901_001.jpg

    device_id\nABC123\nXYZ999
"""
from __future__ import annotations
import argparse
import csv
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List, Set, Tuple
from app.config import load_config

@dataclass
class Targets:
    image_ids: Set[int]
    paths: Set[str]
    filenames: Set[str]
    device_ids: Set[str]


def read_targets(csv_path: Path) -> Targets:
    with open(csv_path, newline="") as f:
        reader = csv.DictReader(f)
        cols = {c.strip().lower() for c in reader.fieldnames or []}
        required = {"image_id", "path", "filename", "device_id"}
        if not cols & required:
            raise ValueError(
                f"CSV must include at least one of columns: {sorted(required)}; got {sorted(cols)}"
            )
        image_ids: Set[int] = set()
        paths: Set[str] = set()
        filenames: Set[str] = set()
        device_ids: Set[str] = set()
        for row in reader:
            if "image_id" in row and row["image_id"].strip():
                try:
                    image_ids.add(int(row["image_id"]))
                except ValueError:
                    raise ValueError(f"Invalid image_id: {row['image_id']}")
            if "path" in row and row["path"].strip():
                paths.add(row["path"].strip())
            if "filename" in row and row["filename"].strip():
                filenames.add(Path(row["filename"].strip()).name)
            if "device_id" in row and row["device_id"].strip():
                device_ids.add(row["device_id"].strip())
        return Targets(image_ids, paths, filenames, device_ids)


def collect_device_ids(conn: sqlite3.Connection, t: Targets) -> Set[str]:
    device_ids: Set[str] = set(t.device_ids)

    # image_id → device_id
    if t.image_ids:
        q = (
                "SELECT DISTINCT device_id FROM images WHERE image_id IN ("
                + ",".join(["?"] * len(t.image_ids))
                + ")"
        )
        rows = conn.execute(q, tuple(sorted(t.image_ids))).fetchall()
        device_ids.update(r[0] for r in rows)

    # path (exact match) → device_id
    if t.paths:
        q = (
                "SELECT DISTINCT device_id FROM images WHERE path IN ("
                + ",".join(["?"] * len(t.paths))
                + ")"
        )
        rows = conn.execute(q, tuple(sorted(t.paths))).fetchall()
        device_ids.update(r[0] for r in rows)

    # filename (basename) → device_id (may match multiple rows)
    if t.filenames:
        placeholders = ",".join(["?"] * len(t.filenames))
        q = f"SELECT DISTINCT device_id FROM images WHERE substr(path, length(path) - instr(reverse(path), '/') + 2) IN ({placeholders}) OR path LIKE '%' || ?"
        # The above is messy across OSes; prefer simpler portable approach instead:
        # Fetch by LIKE matching end-of-path.
        device_rows = []
        for name in t.filenames:
            device_rows += conn.execute(
                "SELECT DISTINCT device_id FROM images WHERE path LIKE ?",
                (f"%/{name}",),
            ).fetchall()
        device_ids.update(r[0] for r in device_rows)

    return {d for d in device_ids if d is not None and str(d) != ""}


def review_ids_for_device_ids(conn: sqlite3.Connection, device_ids: Iterable[str]) -> List[int]:
    device_ids = list(device_ids)
    if not device_ids:
        return []
    placeholders = ",".join(["?"] * len(device_ids))
    q = f"""
        SELECT r.review_id
        FROM reviews r
        JOIN images i ON i.image_id = r.image_id
        WHERE i.device_id IN ({placeholders})
        """
    rows = conn.execute(q, tuple(device_ids)).fetchall()
    return [int(r[0]) for r in rows]


def reset_reviews_and_annotations(conn: sqlite3.Connection, review_ids: List[int], dry_run: bool) -> Tuple[int, int]:
    if not review_ids:
        return (0, 0)
    placeholders = ",".join(["?"] * len(review_ids))

    # Count annotations to be deleted (for logging)
    (ann_cnt,) = conn.execute(
        f"SELECT COUNT(*) FROM annotations WHERE review_id IN ({placeholders})",
        tuple(review_ids),
    ).fetchone()

    if dry_run:
        return (len(review_ids), int(ann_cnt))

    with conn:
        conn.execute("PRAGMA defer_foreign_keys=ON")
        # Remove annotations for those reviews
        conn.execute(
            f"DELETE FROM annotations WHERE review_id IN ({placeholders})",
            tuple(review_ids),
        )
        # Reset the review rows to pristine state
        conn.execute(
            f"""
            UPDATE reviews
               SET status='unassigned',
                   result=NULL,
                   assigned_to=NULL,
                   batch_id=NULL,
                   decided_at=NULL,
                   standard_version=NULL
             WHERE review_id IN ({placeholders})
            """,
            tuple(review_ids),
        )
    return len(review_ids), int(ann_cnt)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    ap.add_argument("--dry-run", action="store_true", help="Preview counts without modifying the DB")
    ap.add_argument("--confirm", action="store_true", help="Required to actually make changes (safety latch)")
    args = ap.parse_args()

    config = load_config()
    db_path = Path(config["DB_PATH"])
    image_root = Path(config["IMAGE_ROOT"])
    out_root = Path(config["OUT_DIR"])
    csv_path = Path(config["CSV_PATH"])

    if not csv_path.exists():
        raise SystemExit(f"CSV not found: {csv_path}")

    targets = read_targets(csv_path)

    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA foreign_keys=ON")
    conn.row_factory = sqlite3.Row

    device_ids = collect_device_ids(conn, targets)
    if not device_ids:
        print("No device_ids resolved from CSV. Nothing to do.")
        return

    rids = review_ids_for_device_ids(conn, device_ids)
    # print(f"Resolved device_ids: {sorted(device_ids)}")
    print(f"Affected reviews: {len(rids)} (annotations will be deleted for these)")

    if args.dry_run:
        # Show a preview of counts
        n_reviews, n_annotations = reset_reviews_and_annotations(conn, rids, dry_run=True)
        print(f"DRY RUN: Would reset {n_reviews} reviews and delete {n_annotations} annotations.")
        return

    if not args.confirm:
        raise SystemExit("Refusing to modify DB without --confirm. Run with --dry-run first to preview.")

    n_reviews, n_annotations = reset_reviews_and_annotations(conn, rids, dry_run=False)
    print(f"DONE: Reset {n_reviews} reviews and deleted {n_annotations} annotations.")


if __name__ == "__main__":
    main()
