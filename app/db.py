import sqlite3, uuid

def connect(db_path: str):
    con = sqlite3.connect(db_path, timeout=30, isolation_level=None)
    con.execute("PRAGMA journal_mode=WAL;")
    con.execute("PRAGMA foreign_keys=ON;")
    return con

def ensure_schema(con, schema_path: str):
    with open(schema_path, "r", encoding="utf-8") as f:
        con.executescript(f.read())

def assign_batch(con, user: str, n: int) -> tuple[str, list[tuple[int, str]]]:
    """Atomically assign n images; returns (batch_id, [(image_id, path), ...])."""
    batch_id = str(uuid.uuid4())
    with con:
        con.execute("BEGIN IMMEDIATE;")
        rows = con.execute("""
            WITH pick AS (
              SELECT image_id FROM reviews
              WHERE status='unassigned'
              ORDER BY RANDOM()
              LIMIT ?
            )
            UPDATE reviews
            SET status='in_progress', assigned_to=?, batch_id=?
            WHERE image_id IN (SELECT image_id FROM pick)
            RETURNING image_id;
        """, (n, user, batch_id)).fetchall()
        con.commit()
    ids = [r[0] for r in rows]
    if not ids: return batch_id, []
    q = "SELECT image_id, path FROM images WHERE image_id IN (%s)" % ",".join("?"*len(ids))
    items = con.execute(q, ids).fetchall()
    return batch_id, items

def record_decision(con, image_id: int, user: str, batch_id: str, result: str, standard_version: str):
    with con:
        con.execute("""
            UPDATE reviews
            SET status='done', result=?, decided_at=datetime('now'), standard_version=?
            WHERE image_id=? AND assigned_to=? AND batch_id=?;
        """, (result, standard_version, image_id, user, batch_id))
