"""Database utilities for the Image Review Tool.

This module provides all data access and schema-evolution logic for the
SQLite database. It is the single point of contact between application logic
and the underlying database, ensuring that reads and writes are consistent,
atomic, and concurrency-safe.

Responsibilities:
  * Open and configure database connections (enabling WAL and foreign keys).
  * Initialize or upgrade the schema (`ensure_schema`, `run_migrations`).
  * Handle batch assignment (`assign_batch`) and decision recording.
  * Manage review rollback (`release_batch`) when a session is canceled.
  * Persist user click annotations (`add_annotation`).

SQLite settings:
  * `isolation_level=None` → autocommit mode.
  * WAL (Write-Ahead Logging) → safe concurrent writes over SMB shares.
  * `PRAGMA foreign_keys=ON` → enforces referential integrity.

All mutations are wrapped in short explicit transactions to avoid race
conditions during multi-user access.
"""

import sqlite3, uuid, os

# ---------------------------------------------------------------------------
# Schema migration helpers
# ---------------------------------------------------------------------------

def _get_user_version(con):
    """Retrieve the current schema version from SQLite PRAGMA."""
    return con.execute("PRAGMA user_version;").fetchone()[0]

def _set_user_version(con, v: int):
    """Set the schema version number in SQLite PRAGMA."""
    con.execute(f"PRAGMA user_version={v};")

def run_migrations(con):
    """Apply incremental migrations to the database schema.

    Uses SQLite's `PRAGMA user_version` to track applied migrations.
    Each migration block should be idempotent and bump the version once
    successfully applied.

    Current migrations:
      v<2 → v=2
        - Remove the CHECK constraint restricting `reviews.result`
          to ('yes','no') to allow arbitrary result labels.
        - Create the `annotations` table if missing.

    Args:
        con: Active SQLite connection (autocommit enabled).
    """
    v = _get_user_version(con)

    # --- Migration to v=2: remove CHECK on reviews.result ---
    if v < 2:
        row = con.execute("""
            SELECT sql FROM sqlite_master
            WHERE type='table' AND name='reviews'
        """).fetchone()
        sql = row[0] if row else ""

        # Old schema had: result TEXT CHECK(result IN ('yes','no'))
        if "result" in sql and "CHECK" in sql and "'yes'" in sql and "'no'" in sql:
            # Do ALL transactional work inside one executescript block
            con.executescript("""
                BEGIN IMMEDIATE;

                CREATE TABLE reviews_new (
                  review_id        INTEGER PRIMARY KEY,
                  image_id         INTEGER NOT NULL REFERENCES images(image_id),
                  status           TEXT NOT NULL CHECK(status IN ('unassigned','in_progress','done')),
                  assigned_to      TEXT,
                  batch_id         TEXT,
                  result           TEXT,
                  standard_version TEXT,
                  decided_at       TEXT
                );

                INSERT INTO reviews_new
                  (review_id,image_id,status,assigned_to,batch_id,result,standard_version,decided_at)
                SELECT review_id,image_id,status,assigned_to,batch_id,result,standard_version,decided_at
                FROM reviews;

                DROP TABLE reviews;
                ALTER TABLE reviews_new RENAME TO reviews;

                PRAGMA user_version=2;
                
                CREATE TABLE IF NOT EXISTS annotations (
                    ann_id     INTEGER PRIMARY KEY,
                    review_id  INTEGER NOT NULL REFERENCES reviews(review_id),
                    x_norm     REAL NOT NULL,  -- 0..1 in original image space
                    y_norm     REAL NOT NULL,  -- 0..1 in original image space
                    button     TEXT CHECK(button IN ('left','right')) NOT NULL,
                    created_at TEXT NOT NULL
                );
                COMMIT;
            """)
        else:
            # Already in new shape; just bump the version without extra COMMITs
            _set_user_version(con, 2)



# ---------------------------------------------------------------------------
# Core connection and schema utilities
# ---------------------------------------------------------------------------

def connect(db_path: str):
    """Open a SQLite connection with standard PRAGMA settings.

    Ensures parent directories exist before opening, and configures WAL and
    foreign-key enforcement. Connection is autocommit by default.

    Args:
        db_path: Absolute or relative path to the SQLite database file.

    Returns:
        sqlite3.Connection: Configured database connection.

    Raises:
        RuntimeError: If SQLite cannot open the database.
    """
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
    """Create all tables if they don't exist using the provided schema.

    Args:
        con: SQLite connection.
        schema_path: Path to `schema.sql`.
    """
    with open(schema_path, "r", encoding="utf-8") as f:
        con.executescript(f.read())

# ---------------------------------------------------------------------------
# Review workflow management
# ---------------------------------------------------------------------------

def assign_batch(con, user: str, n: int, qc_rate: float = 0.10):
    """Assign a new batch of reviews to a user.

    Selects up to `n` unassigned review rows, balancing QC and non-QC items
    based on `qc_rate`, and marks them as `in_progress` for this user.

    Args:
        con: SQLite connection.
        user: Username requesting the batch.
        n: Number of images to review.
        qc_rate: Fraction of QC items desired.

    Returns:
        tuple[str, list[tuple]]:
            (batch_id, items)
            batch_id — UUID identifying this batch
            items — [(review_id, image_id, path, device_id, qc_flag), ...]
    """
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

def release_batch(con, user: str, batch_id: str):
    """Release any 'in_progress' reviews for this batch back to the pool.

    Used when a reviewer exits early (e.g., presses Esc) to ensure their
    uncompleted items are not locked indefinitely.

    Args:
        con: SQLite connection.
        user: Username releasing the batch.
        batch_id: The batch UUID currently in progress.
    """
    with con:
        con.execute(
            """
            UPDATE reviews
            SET status='unassigned', assigned_to=NULL, batch_id=NULL
            WHERE batch_id=? AND assigned_to=? AND status='in_progress';
            """,
            (batch_id, user),
        )

def record_decision(
    con, review_id: int, user: str, batch_id: str, result: str, standard_version: str
):
    """Mark a review as completed and record the decision.

    Args:
        con: SQLite connection.
        review_id: ID of the review to finalize.
        user: Username making the decision.
        batch_id: Active batch identifier.
        result: Decision label (e.g., 'yes', 'no', 'skip').
        standard_version: Current app or evaluation standard version.
    """
    with con:
        con.execute(
            """
            UPDATE reviews
            SET status='done', result=?, decided_at=datetime('now'), standard_version=?
            WHERE review_id=? AND assigned_to=? AND batch_id=?;
        """,
            (result, standard_version, review_id, user, batch_id),
        )

def add_annotation(con, review_id: int, x_norm: float, y_norm: float, button: str):
    """Insert a spatial annotation (click) for a review.

    Each record represents one user click, stored with normalized coordinates.

    Args:
        con: SQLite connection.
        review_id: ID of the review associated with the click.
        x_norm: Horizontal position in normalized [0,1] image space.
        y_norm: Vertical position in normalized [0,1] image space.
        button: 'left' or 'right' — the mouse button clicked.
    """
    with con:
        con.execute(
            """
            INSERT INTO annotations(review_id, x_norm, y_norm, button, created_at)
            VALUES (?, ?, ?, ?, datetime('now'));
            """,
            (review_id, float(x_norm), float(y_norm), button),
        )