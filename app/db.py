import sqlite3, uuid, os


def connect(db_path: str):
    # Ensure the parent directory exists (SQLite won't create folders)
    parent = os.path.dirname(db_path)
    if parent and not os.path.isdir(parent):
        os.makedirs(parent, exist_ok=True)

    try:
        con = sqlite3.connect(db_path, timeout=15, isolation_level=None)
    except sqlite3.OperationalError as e:
        raise RuntimeError(
            f"SQLite failed to open: {db_path}\n"
            f"Dir exists: {os.path.isdir(parent)} | "
            f"Writable: {os.access(parent, os.W_OK)}\n"
            f"Original error: {e}"
        ) from e

    con.execute("PRAGMA journal_mode=WAL;")
    con.execute("PRAGMA foreign_keys=ON;")
    return con


def ensure_schema(con, schema_path: str):
    with open(schema_path, "r", encoding="utf-8") as f:
        con.executescript(f.read())


def assign_batch(con, user: str, n: int, qc_rate: float = 0.10):
    batch_id = str(uuid.uuid4())
    target_qc = max(1, round(n * qc_rate))
    target_non = n - target_qc

    with con:
        con.execute("BEGIN IMMEDIATE;")

        # 1) QC pool
        qc_rows = con.execute(
            """
            WITH pool AS (
              SELECT r.review_id
              FROM reviews r
              JOIN images i ON i.image_id = r.image_id
              WHERE r.status='unassigned'
                AND i.qc_flag=1
                -- don't give both QC rows of the same image to the same user
                AND NOT EXISTS (
                  SELECT 1 FROM reviews r2
                  WHERE r2.image_id = r.image_id AND r2.assigned_to = ?
                )
              ORDER BY RANDOM()
              LIMIT ?
            )
            UPDATE reviews
            SET status='in_progress', assigned_to=?, batch_id=?
            WHERE review_id IN (SELECT review_id FROM pool)
            RETURNING review_id;
        """,
            (user, target_qc, user, batch_id),
        ).fetchall()

        got_qc = len(qc_rows)

        # 2) Non-QC pool (and also any QC leftovers if not enough QC available)
        non_rows = con.execute(
            """
            WITH pool AS (
              SELECT r.review_id
              FROM reviews r
              JOIN images i ON i.image_id = r.image_id
              WHERE r.status='unassigned'
                AND (
                      i.qc_flag=0
                   OR ? > 0  -- allow topping up with QC if we couldn't get enough
                )
                AND NOT EXISTS (
                  SELECT 1 FROM reviews r2
                  WHERE r2.image_id = r.image_id AND r2.assigned_to = ?
                )
              ORDER BY RANDOM()
              LIMIT ?
            )
            UPDATE reviews
            SET status='in_progress', assigned_to=?, batch_id=?
            WHERE review_id IN (SELECT review_id FROM pool)
            RETURNING review_id;
        """,
            (
                target_qc - got_qc,
                user,
                target_non + max(0, target_qc - got_qc),
                user,
                batch_id,
            ),
        ).fetchall()

        con.execute("COMMIT;")

    # Fetch the images for the picked review_ids
    picked_ids = [r[0] for r in qc_rows] + [r[0] for r in non_rows]
    if not picked_ids:
        return batch_id, []

    q = f"""
      SELECT r.review_id, i.image_id, i.path, i.device_id, i.qc_flag
      FROM reviews r JOIN images i ON i.image_id = r.image_id
      WHERE r.review_id IN ({",".join("?" * len(picked_ids))})
    """
    items = con.execute(q, picked_ids).fetchall()
    # return [(review_id, image_id, path, device_id, qc_flag), ...]
    return batch_id, items


def record_decision(
    con, review_id: int, user: str, batch_id: str, result: str, standard_version: str
):
    with con:
        con.execute(
            """
            UPDATE reviews
            SET status='done', result=?, decided_at=datetime('now'), standard_version=?
            WHERE review_id=? AND assigned_to=? AND batch_id=?;
        """,
            (result, standard_version, review_id, user, batch_id),
        )
