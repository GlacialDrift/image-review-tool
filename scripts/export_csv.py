import csv
from app.config import load_config
from app.db import connect

def main():
    cfg = load_config()
    con = connect(cfg["DB_PATH"])
    rows = con.execute("""
      SELECT i.device_id, i.path, r.assigned_to, r.decided_at, r.result, r.standard_version
      FROM reviews r JOIN images i USING(image_id)
      WHERE r.status='done'
      ORDER BY r.decided_at
    """).fetchall()
    with open("decisions.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["device_id", "path", "user", "timestamp", "result", "standard_version"])
        w.writerows(rows)
    print("Wrote decisions.csv")

if __name__ == "__main__":
    main()
