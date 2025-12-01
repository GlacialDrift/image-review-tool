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
--   4. devices       — table of unique devices and their overall decision
--
-- Conventions:
--   * All timestamps are stored in UTC using SQLite's `datetime('now')`.
--   * Foreign keys are enforced; deletions should cascade manually if required.
--   * CHECK constraints limit enumerated fields to valid symbolic values.
--   * Numeric flags (e.g., qc_flag) are used for performance and simplicity.
--
-- Relationships:
--   devices (1)───(∞) images (1)───(∞) reviews (1)───(∞) annotations
--
-- The schema is intentionally simple and portable to support multi-user access
-- over SMB shares using SQLite's WAL mode.
-- =============================================================================


-- ============================================================
-- v2.0
-- ============================================================
-- Schema for balloon coating image review with device-level results
-- and optimized workflow (variant-priority and auto-skip rules).
-- ============================================================

PRAGMA foreign_keys=ON;

-- ---------------------------------------------------------------------------
-- Table: images
-- ---------------------------------------------------------------------------
-- Each unique image in the review corpus, one row per image file
-- device_id  — an identifier derived from filename or metadata
-- sha256     — content hash for integrity and duplicate detection
-- qc_flag    — marks roughly 10% of images as duplicates for quality control
CREATE TABLE IF NOT EXISTS images (
  image_id      INTEGER PRIMARY KEY AUTOINCREMENT,
  device_id     TEXT NOT NULL, -- 11-digit ID parsed from filename
  variant       TEXT NOT NULL, -- 3-digit image suffix, zero padded
  path          TEXT UNIQUE NOT NULL, -- filesystem path to image
  qc_flag       INTEGER NOT NULL DEFAULT 0,   -- 1 if image is part of QC sampling
  registered_at TEXT DEFAULT (datetime('now')),
  sha256        TEXT UNIQUE NOT NULL,
  UNIQUE (device_id, variant) -- each device-variant pair should be unique
);

-- Helpful indexes for device/variant-based queries
CREATE INDEX idx_images_device ON images(device_id);
CREATE INDEX idx_images_device_variant ON images(device_id, variant);

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
  review_id       INTEGER PRIMARY KEY AUTOINCREMENT,
  image_id        INTEGER NOT NULL,
  status          TEXT NOT NULL DEFAULT 'unassigned' CHECK(status IN ('unassigned','in_progress','done')),
  result          TEXT, -- 'yes', 'no', 'skip', 'auto_skip_device_yes', 'auto_skip_no_skip_pattern', etc.
  assigned_to     TEXT, -- reviewer id
  batch_id        TEXT, -- logical batch id
  standard_version TEXT, -- reference to script version
  decided_at      TEXT, -- datetime when decision was made
  notes           TEXT, -- optional free-text notes/audit info
  FOREIGN KEY (image_id) REFERENCES images(image_id) ON DELETE CASCADE
);

CREATE INDEX idx_reviews_image ON reviews(image_id);
CREATE INDEX idx_reviews_status ON reviews(status);

-- ------------------------------------------------------------
-- Table: devices
-- One row per device_id capturing the device-level final outcome.
-- ------------------------------------------------------------

CREATE TABLE IF NOT EXISTS devices (
    device_id            TEXT PRIMARY KEY,  -- same as images.device_id
    final_result         TEXT,              -- 'yes', 'no', 'unknown'
    final_decision_source TEXT,             -- image_id or rule name, e.g. 'no_skip_skip_rule'
    decided_at           TEXT,              -- datetime when device-level result was set
    notes                TEXT               -- optional notes
);

-- Optional index if you ever want to filter by result quickly
CREATE INDEX idx_devices_final_result ON devices(final_result);

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
