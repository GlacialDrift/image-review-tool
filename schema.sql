PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS images (
  image_id      INTEGER PRIMARY KEY,
  path          TEXT UNIQUE NOT NULL,
  device_id     TEXT NOT NULL,
  sha256        TEXT NOT NULL,
  registered_at TEXT NOT NULL,
  qc_flag       INTEGER NOT NULL DEFAULT 0   -- 0 = normal, 1 = QC duplicate
);

CREATE TABLE IF NOT EXISTS reviews (
  review_id       INTEGER PRIMARY KEY,
  image_id        INTEGER NOT NULL REFERENCES images(image_id),
  status          TEXT NOT NULL CHECK(status IN ('unassigned','in_progress','done')),
  assigned_to     TEXT,
  batch_id        TEXT,
  result          TEXT CHECK(result IN ('yes','no')),
  standard_version TEXT,
  decided_at      TEXT
);

CREATE TABLE IF NOT EXISTS qc_reviews (
  qc_id      INTEGER PRIMARY KEY,
  image_id   INTEGER NOT NULL REFERENCES images(image_id),
  reviewer   TEXT NOT NULL,
  result     TEXT CHECK(result IN ('yes','no')),
  decided_at TEXT NOT NULL
);
