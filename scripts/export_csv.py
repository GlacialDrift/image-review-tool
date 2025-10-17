import csv
from app.config import load_config
from app.db import connect


def main():
    cfg = load_config()
    con = connect(cfg["DB_PATH"])
    rows = con.execute("""
      SELECT i.device_id, r.review_id, r.image_id, i.path, r.assigned_to, r.batch_id, r.decided_at, r.result, r.standard_version, i.qc_flag
      FROM reviews r JOIN images i USING(image_id)
      WHERE r.status='done'
      ORDER BY r.decided_at
    """).fetchall()
    with open("decisions.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(
            ["device_id", "review id", "image id", "path", "user", "review batch", "timestamp", "Loss of Coating Observed?", "ImageReview_version", "QC"]
        )
        w.writerows(rows)
    print("Wrote decisions.csv")


if __name__ == "__main__":
    main()
