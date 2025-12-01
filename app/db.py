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
                -- AND i.variant = '000'
                -- don't give both QC rows of the same image to the same user
                AND NOT EXISTS (
                  SELECT 1 FROM reviews r2
                  WHERE r2.image_id = r.image_id AND r2.assigned_to = ?
                )
              ORDER BY i.variant ASC, RANDOM()
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
                -- AND i.variant = '000'
                AND (
                      i.qc_flag=0
                   OR ? > 0  -- allow topping up with QC if we couldn't get enough
                )
                AND NOT EXISTS (
                  SELECT 1 FROM reviews r2
                  WHERE r2.image_id = r.image_id AND r2.assigned_to = ?
                )
              ORDER BY i.variant ASC, RANDOM()
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
      ORDER BY i.variant, RANDOM()
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

def get_device_review_results(con, device_id: str):
    """Return completed review results for a device, ordered by variant.

    Returns a list of (variant, result) for all reviews on this device where
    status='done' and result is not NULL, ordered by images.variant ASC.

    This is used by the NO–SKIP–SKIP pattern logic.
    """
    rows = con.execute(
        """
        SELECT i.variant, r.result
        FROM reviews r
        JOIN images i ON i.image_id = r.image_id
        WHERE i.device_id = ?
          AND r.status = 'done'
          AND r.result IS NOT NULL
        ORDER BY i.variant ASC, r.review_id ASC;
        """,
        (device_id,),
    ).fetchall()
    return rows  # e.g. [('000', 'no'), ('001', 'skip'), ('002', 'skip')]

def auto_skip_remaining_for_device(
    con,
    device_id: str,
    user: str,
    batch_id: str | None,
    standard_version: str,
    result_code: str,
):
    """Mark all remaining reviews for a device as done with an auto-skip result.

    This is used for:
      * YES rule:     result_code = 'auto_skip_device_yes'
      * NO–SKIP–SKIP: result_code = 'repeated_skip_pattern'
    """
    with con:
        con.execute(
            """
            UPDATE reviews
            SET status = 'done',
                result = ?,
                decided_at = datetime('now'),
                standard_version = COALESCE(standard_version, ?),
                assigned_to = COALESCE(assigned_to, ?),
                batch_id = COALESCE(batch_id, ?)
            WHERE image_id IN (
                SELECT image_id FROM images WHERE device_id = ?
            )
              AND status != 'done';
            """,
            (result_code, standard_version, user, batch_id, device_id),
        )

def update_device_final_result(
    con,
    device_id: str,
    final_result: str,
    decision_source: str,
    notes: str | None = None,
):
    """Update the device-level final result.

    final_result: 'yes', 'no', or 'unknown'
    decision_source: image_id or rule name (e.g. 'no_skip_skip_rule')
    """
    with con:
        con.execute(
            """
            UPDATE devices
            SET final_result = ?,
                final_decision_source = ?,
                decided_at = datetime('now'),
                notes = COALESCE(notes, ?)
            WHERE device_id = ?;
            """,
            (final_result, decision_source, notes, device_id),
        )

def finalize_device_yes(
    con,
    device_id: str,
    image_id: int,
    user: str,
    batch_id: str | None,
    standard_version: str,
):
    """Apply YES rule: mark device yes and auto-skip remaining images."""
    auto_skip_remaining_for_device(
        con,
        device_id=device_id,
        user=user,
        batch_id=batch_id,
        standard_version=standard_version,
        result_code="auto_skip_device_yes",
    )
    update_device_final_result(
        con,
        device_id=device_id,
        final_result="yes",
        decision_source=str(image_id),
        notes="triggered_by: yes_decision",
    )

def finalize_device_no_by_pattern(
    con,
    device_id: str,
    user: str,
    batch_id: str | None,
    standard_version: str,
):
    """Apply NO–SKIP–SKIP rule: mark device no and auto-skip remaining images."""
    auto_skip_remaining_for_device(
        con,
        device_id=device_id,
        user=user,
        batch_id=batch_id,
        standard_version=standard_version,
        result_code="repeated_skip_pattern",
    )
    update_device_final_result(
        con,
        device_id=device_id,
        final_result="no",
        decision_source="repeated_skip_rule",
        notes="triggered_by: repeated_skip_pattern",
    )


def _is_zero_variant(path: str) -> bool:
    """Check whether a file path corresponds to a `_000` image variant.

    Args:
        path: Full filesystem path or filename of the image.

    Returns:
        bool: True if the path ends with `_000.jpg` or `_000.jpeg` (case-insensitive);
        otherwise False.

    Notes:
        `_000` images represent the primary variant of each device pair and are
        the only ones assigned for initial review batches.
    """
    p = path.lower()
    return p.endswith("_000.jpg") or p.endswith("_000.jpeg")





# ---------------------------------------------------------------------------
# Old pair assignment logic for reviewing only _000.jpg and _001.jpg images
# ---------------------------------------------------------------------------



def _pair_path_for_zero(path: str) -> str | None:
    """Derive the `_001` counterpart path for a given `_000` image.

    Args:
        path: Path or filename of the `_000` image.

    Returns:
        str | None: The corresponding `_001` path (same directory and extension)
        if the input path ends with `_000.jpg` or `_000.jpeg`; otherwise None.

    Example:
        >>> _pair_path_for_zero("images/12345678901_000.jpg")
        'images/12345678901_001.jpg'
    """
    # Returns the _001 image path by changing the suffix without changing the file extension
    p = path.lower()
    if p.endswith("_000.jpg"):
        return path[:-8] + "_001.jpg"
    elif p.endswith("_000.jpeg"):
        return path[:-9] + "_001.jpeg"
    return None

def _fetch_pair_review(con, path_zero: str):
    """Retrieve the active (not 'done') review row for the paired `_001` image.

    Args:
        con: Active SQLite connection.
        path_zero: Full path to the `_000` image used to infer the `_001` pair.

    Returns:
        tuple | None:
            The first matching row tuple `(review_id, image_id, path, device_id, qc_flag)`
            for the paired `_001` image if a not-yet-completed review exists,
            otherwise None.

    Notes:
        - This function joins the `images` and `reviews` tables to find the pair.
        - It orders by `rowid ASC` to ensure deterministic selection if multiple
          rows exist (e.g., QC duplicates).
    """
    pair_path = _pair_path_for_zero(path_zero)
    if not pair_path:
        return None
    row = con.execute(
        """
        SELECT r.review_id, i.image_id, i.path, i.device_id, i.qc_flag
        FROM images i
        JOIN reviews r USING(image_id)
        WHERE i.path=? AND r.status!='done'
        ORDER BY r.rowid ASC
        LIMIT 1
        """,
        (pair_path,),
    ).fetchone()
    return row

def auto_skip_pair(con, path_zero: str, standard_version: str, user: str, batch_id: str):
    """Mark the `_001` paired image as 'skip' when its `_000` counterpart is finalized.

    Args:
        con: Active SQLite connection.
        path_zero: Path to the `_000` image whose pair should be skipped.
        standard_version: Current standard version string (e.g., app revision or SOP version).
        user: Username of the reviewer marking the `_000` decision.
        batch_id: UUID of the current review batch.

    Behavior:
        If an unfinished `_001` review exists for the same device, this function:
          * Updates its `status` to `'done'`
          * Sets `result='skip'`
          * Stamps `decided_at=datetime('now')`
          * Records `standard_version`, `assigned_to`, and `batch_id`

    Returns:
        None
    """
    pair = _fetch_pair_review(con, path_zero)
    if not pair:
        return
    pair_review_id = pair[0]
    with con:
        con.execute(
            """
            UPDATE reviews
            SET status='done', 
                result='skip', 
                decided_at=datetime('now'), 
                standard_version=?,
                assigned_to=?,
                batch_id=?
            WHERE review_id=? AND status!='done';
            """,
            (standard_version, user, batch_id, pair_review_id),
        )

def assign_pair_now(con, path_zero: str, user: str, batch_id: str):
    """Assign the `_001` paired image for immediate review and return its metadata tuple.

    Args:
        con: Active SQLite connection.
        path_zero: Path to the `_000` image whose `_001` pair should be queued.
        user: Username of the current reviewer.
        batch_id: UUID identifying the active review batch.

    Returns:
        tuple | None:
            The review tuple `(review_id, image_id, path, device_id, qc_flag)`
            for the `_001` image if found and reassigned; otherwise None.

    Notes:
        - Used when the reviewer marks `_000` as 'skip', prompting the `_001` to
          appear next in the session.
        - The pair review row’s `status` is updated to `'in_progress'` and stamped
          with the same `assigned_to` and `batch_id`.
    """
    pair = _fetch_pair_review(con, path_zero)
    if not pair:
        return None
    pair_review_id = pair[0]
    with con:
        con.execute(
            """
            UPDATE reviews
            SET status='in_progress', assigned_to=?, batch_id=?
            WHERE review_id=? AND status!='done';
            """,
            (user, batch_id, pair_review_id),
        )
    # return the same tuple shape App expects: (review_id, image_id, path, device_id, qc_flag)
    return con.execute(
        """
        SELECT r.review_id, i.image_id, i.path, i.device_id, i.qc_flag
        FROM reviews r JOIN images i USING(image_id)
        WHERE r.review_id=?;
        """,
        (pair_review_id,),
    ).fetchone()