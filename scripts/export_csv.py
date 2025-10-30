"""Export finalized image review results to a CSV file.

This utility queries the SQLite database for all completed (`status='done'`)
review rows, joins them to their corresponding image metadata, and writes
the combined records to `decisions.csv` in the current working directory.

Intended usage:
    python export_csv.py
or:
    python -m export_csv

The resulting CSV can be shared with downstream analysis pipelines
(e.g., inter-rater agreement checks, QC evaluation, or manufacturing reports).

Output columns:
    device_id          — extracted from the image filename
    review id          — primary key from the reviews table
    image id           — foreign key reference to the images table
    path               — full filesystem path to the reviewed image
    user               — reviewer username
    review batch       — UUID identifying the batch assignment
    timestamp          — UTC timestamp when the review was completed
    Result             — recorded decision label (yes/no/skip/other)
    ImageReview_version — version string from configuration
    QC                 — 1 if image was a QC duplicate, else 0
"""

import csv
import os.path

from app.config import load_config
from app.db import connect


def main():
    """Query all completed reviews and export them to `decisions.csv`.

    Steps:
      1. Load configuration to obtain the database path.
      2. Establish a read-only SQLite connection (via app.db.connect).
      3. Run a SELECT query joining `reviews` and `images`:
           - Includes only rows where `reviews.status='done'`.
           - Orders by decision timestamp for chronological reporting.
      4. Write all rows to a UTF-8 encoded CSV file named `decisions.csv`.

    The file is overwritten each time the script runs.

    Raises:
      sqlite3.Error: If the database query fails.
      OSError: If the file cannot be written to disk.
    """
    cfg = load_config()
    con = connect(cfg["DB_PATH"])
    rows = con.execute("""
      SELECT i.device_id, i.variant, r.review_id, r.image_id, i.path, r.assigned_to, r.batch_id, r.decided_at, r.result, r.standard_version, i.qc_flag
      FROM reviews r JOIN images i USING(image_id)
      WHERE r.status='done'
      ORDER BY r.decided_at
    """).fetchall()
    out_path = os.path.dirname(cfg["DB_PATH"])
    out_path += "/decisions.csv"
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(
            ["device_id", "variant", "review id", "image id", "path", "user", "review batch", "timestamp", "Result", "ImageReview_version", "QC"]
        )
        w.writerows(rows)
    print("Wrote decisions.csv to root directory specified in config.ini")


if __name__ == "__main__":
    main()
