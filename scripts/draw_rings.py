
"""
Export copies of images that have review annotations and draw rings at the annotated locations.

- Connects to the existing SQLite DB (schema with images, reviews, annotations)
- Gathers normalized coordinates from `annotations` joined to `reviews` and `images`
- Converts normalized (x, y) to pixel coordinates in ORIGINAL image space
- Draws configurable rings around each point
- Writes copies to an output directory (preserving folder structure by default)
- Emits a CSV manifest of outputs

Typical usage:
    python export_annotations_draw_rings.py \
        --db path/to/reviews.db \
        --image-root /absolute/path/to/images_root \
        --out-root /path/to/output_dir \
        --radius-pct 0.02 --min-radius 6 --double-outline

If your reviewer displayed auto-rotated (EXIF) images and coordinates were captured in the displayed orientation,
pass --exif-transpose so we draw in that same orientation.

By default, outputs are merged per image (all points for a given image are drawn to one copy),
but you can switch to per-review outputs with --per-review.
"""
from __future__ import annotations
import argparse
import csv
import sqlite3
import os
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Tuple

from PIL import Image, ImageDraw

from app.config import load_config


@dataclass
class Point:
    x_norm: float
    y_norm: float

@dataclass
class AnnRecord:
    image_id: int
    image_path: str
    review_id: int
    outcome: str
    points: List[Point]


def clamp01(v: float) -> float:
    return 0.0 if v < 0 else 1.0 if v > 1 else v


def norm_to_px(x: float, y: float, width: int, height: int) -> Tuple[int, int]:
    x = clamp01(x)
    y = clamp01(y)
    # Map [0,1] inclusive to pixel indices [0, W-1], [0, H-1]
    x_px = int(round(x * (max(1, width) - 1)))
    y_px = int(round(y * (max(1, height) - 1)))
    return x_px, y_px


def fetch_annotations(conn: sqlite3.Connection) -> List[AnnRecord]:
    """Return one row per (image_id, review_id) with all points grouped."""
    q = (
        """
        SELECT i.image_id,
               i.path AS image_path,
               r.review_id,
               COALESCE(r.result, '') AS outcome,
               a.x_norm,
               a.y_norm
        FROM annotations a
        JOIN reviews r ON r.review_id = a.review_id
        JOIN images  i ON i.image_id  = r.image_id
        ORDER BY i.image_id, r.review_id, a.ann_id
        """
    )
    rows = conn.execute(q).fetchall()
    grouped: Dict[Tuple[int, int, str, str], List[Point]] = defaultdict(list)
    for image_id, image_path, review_id, outcome, x, y in rows:
        grouped[(image_id, review_id, image_path, outcome)].append(Point(float(x), float(y)))

    out: List[AnnRecord] = []
    for (image_id, review_id, image_path, outcome), pts in grouped.items():
        out.append(AnnRecord(
            image_id=image_id,
            image_path=image_path,
            review_id=review_id,
            outcome=outcome or "",
            points=pts,
        ))
    return out


def group_records(records: List[AnnRecord], per_review: bool) -> Iterable[Tuple[str, int, List[AnnRecord]]]:
    """
    Yield groups for output.
    If per_review=False (default): group by image_path (merge all reviews' points to one output).
    If per_review=True: each (image_id, review_id) is its own output.
    Returns tuples of (group_key, image_id, recs)
    """
    if per_review:
        for rec in records:
            key = f"{rec.image_path}::review:{rec.review_id}"
            yield key, rec.image_id, [rec]
    else:
        groups: Dict[str, List[AnnRecord]] = defaultdict(list)
        img_ids: Dict[str, int] = {}
        for rec in records:
            groups[rec.image_path].append(rec)
            img_ids.setdefault(rec.image_path, rec.image_id)
        for k, v in groups.items():
            yield k, img_ids[k], v


def ensure_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def draw_ring(draw: ImageDraw.ImageDraw, cx: int, cy: int, radius: int, outline: str, width: int) -> None:
    bbox = (cx - radius, cy - radius, cx + radius, cy + radius)
    draw.ellipse(bbox, outline=outline, width=width)


def draw_rings_on_image(img: Image.Image, points_px: List[Tuple[int, int]], radius: int, line_width: int) -> None:
    convert_back = (img.mode != "RGBA")
    base = img.convert("RGBA") if convert_back else img

    overlay = Image.new("RGBA", base.size, (0,0,0,0))
    draw = ImageDraw.Draw(overlay)
    # Outer ring (contrasting edge), then inner ring
    for x, y in points_px:
        draw_ring(draw, x, y, radius + 1, outline="#00000080", width=1)
        draw_ring(draw, x, y, radius, outline="#ffff0080", width=max(1, line_width))

    result = Image.alpha_composite(base, overlay)
    if convert_back:
        img.paste(result.convert(img.mode))
    else:
        img.paste(result)


def resolve_input_path(image_path_in_db: str, image_root: Path) -> Path:
    p = Path(image_path_in_db)
    if not p.is_absolute():
        return image_root / p
    return p


def make_output_path(src_path: Path, out_root: Path, image_root: Path, suffix: str) -> Path:
    try:
        rel = src_path.relative_to(image_root)
    except ValueError:
        # src is not under image_root; replicate parent structure under out_root using name only
        rel = src_path.name
    stem = src_path.stem
    new_name = f"{stem}{suffix}.png"
    if isinstance(rel, Path):
        return out_root / rel.parent / new_name
    else:
        return out_root / new_name


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    ap.add_argument("--dry-run", action="store_true", help="Do not write images, only print and write CSV plan")

    args = ap.parse_args()

    config = load_config()
    db_path = Path(config["DB_PATH"])
    image_root = Path(config["IMAGE_ROOT"])
    out_root = Path(config["OUT_DIR"])
    csv_path = Path(config["CSV_PATH"])

    out_root.mkdir(parents=True, exist_ok=True)
    csv_path.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row

    records = fetch_annotations(conn)
    if not records:
        print("No annotations found. Nothing to do.")
        return

    n_written = 0
    n_skipped = 0
    n_missing = 0

    with open(csv_path, "w", newline="") as fcsv:
        writer = csv.writer(fcsv)
        writer.writerow([
            "image_id", "review_id_list", "n_reviews_merged", "n_points_total",
            "src_path", "out_path", "outcome_list", "points_px"
        ])

        for group_key, image_id, recs in group_records(records, False):
            # Accumulate points and outcomes for this output
            outcomes: List[str] = []
            pts_norm: List[Tuple[float, float]] = []
            review_ids: List[int] = []
            # All recs share same image_path in both modes
            image_path_in_db = recs[0].image_path
            src_path = resolve_input_path(image_path_in_db, image_root)

            for r in recs:
                review_ids.append(r.review_id)
                if r.outcome:
                    outcomes.append(str(r.outcome))
                for p in r.points:
                    pts_norm.append((p.x_norm, p.y_norm))

            if not src_path.exists():
                print(f"[MISSING] {src_path}")
                n_missing += 1
                continue

            # Load image
            try:
                img = Image.open(src_path)
                img.load()  # force read
            except Exception as e:
                print(f"[ERROR] Failed to open {src_path}: {e}")
                n_missing += 1
                continue

            w, h = img.size
            radius = 30
            lw = 10

            # Convert all points to pixel coordinates
            pts_px = [norm_to_px(x, y, w, h) for (x, y) in pts_norm]

            # Prepare output path
            suffix = f"_ann"
            out_path = make_output_path(src_path, out_root, image_root, suffix)
            ensure_parent(out_path)

            if not args.dry_run:
                img_copy = img.copy()
                draw_rings_on_image(img_copy, pts_px, radius, lw)
                try:
                    img_copy.save(out_path)
                except Exception as e:
                    print(f"[ERROR] Failed to save {out_path}: {e}")
                    n_missing += 1
                    continue
            print(f"[WRITE] {out_path}  (points: {len(pts_px)})")
            n_written += 1

            # Log CSV row (even on skip, to have a manifest)
            writer.writerow([
                image_id,
                ";".join(str(x) for x in review_ids),
                len(recs),
                len(pts_px),
                str(src_path),
                str(out_path),
                ";".join(outcomes) if outcomes else "",
                ";".join(f"({x},{y})" for (x, y) in pts_px),
            ])

    print("")
    print(f"Done. Wrote: {n_written}, Skipped (exists): {n_skipped}, Missing/Errors: {n_missing}")
    print(f"CSV manifest: {csv_path}")


if __name__ == "__main__":
    main()
