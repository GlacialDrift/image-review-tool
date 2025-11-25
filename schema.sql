-- =============================================================================
-- Image Review Tool Database Schema
-- =============================================================================
-- This schema defines the relational structure for the multi-user image review
-- application. It uses SQLite with WAL journaling and foreign-key enforcement
-- (see `PRAGMA foreign_keys=ON` at the top).
--
-- Tables:
--   1. images        — registry of all image files known to the system
--   2. reviews       — review workflow and user decisions
--   3. annotations   — optional click-based spatial annotations on images
--
-- Conventions:
--   * All timestamps are stored in UTC using SQLite's `datetime('now')`.
--   * Foreign keys are enforced; deletions should cascade manually if required.
--   * CHECK constraints limit enumerated fields to valid symbolic values.
--   * Numeric flags (e.g., qc_flag) are used for performance and simplicity.
--
-- Relationships:
--   images (1)───(∞) reviews (1)───(∞) annotations
--
-- The schema is intentionally simple and portable to support multi-user access
-- over SMB shares using SQLite's WAL mode.
-- =============================================================================

PRAGMA foreign_keys=ON;

-- ---------------------------------------------------------------------------
-- Table: images
-- ---------------------------------------------------------------------------
-- Each unique image in the review corpus.
-- device_id  — an identifier derived from filename or metadata
-- sha256     — content hash for integrity and duplicate detection
-- qc_flag    — marks roughly 10% of images as duplicates for quality control
CREATE TABLE IF NOT EXISTS images (
  image_id      INTEGER PRIMARY KEY,
  path          TEXT UNIQUE NOT NULL,
  device_id     TEXT NOT NULL,
  variant       TEXT NOT NULL,
  sha256        TEXT UNIQUE NOT NULL,
  registered_at TEXT NOT NULL,
  qc_flag       INTEGER NOT NULL DEFAULT 0   -- 0 = normal, 1 = QC duplicate
);

-- ---------------------------------------------------------------------------
-- Table: reviews
-- ---------------------------------------------------------------------------
-- The central workflow table. Each row represents one user’s review task
-- for a given image. QC duplicates result in two rows sharing the same
-- image_id but assigned to different reviewers.
--
-- status ∈ {unassigned, in_progress, done}
-- result — free-text label (yes, no, skip, etc.) defined in configuration.
-- batch_id — UUID grouping the reviews fetched together by assign_batch().
CREATE TABLE IF NOT EXISTS reviews (
  review_id       INTEGER PRIMARY KEY,
  image_id        INTEGER NOT NULL REFERENCES images(image_id),
  status          TEXT NOT NULL CHECK(status IN ('unassigned','in_progress','done')),
  assigned_to     TEXT,
  batch_id        TEXT,
  result          TEXT,
  standard_version TEXT,
  decided_at      TEXT
);

-- ---------------------------------------------------------------------------
-- Table: annotations
-- ---------------------------------------------------------------------------
-- Optional per-click annotations tied to specific review rows.
-- Coordinates are normalized to the [0,1] range in original image space.
-- button ∈ {'left','right'} corresponds to the mouse button used.
CREATE TABLE IF NOT EXISTS annotations (
  ann_id     INTEGER PRIMARY KEY,
  review_id  INTEGER NOT NULL REFERENCES reviews(review_id),
  x_norm     REAL NOT NULL,  -- 0..1 in original image space
  y_norm     REAL NOT NULL,  -- 0..1 in original image space
  button     TEXT CHECK(button IN ('left','right')) NOT NULL,
  created_at TEXT NOT NULL
);
