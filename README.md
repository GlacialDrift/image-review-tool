---
Author: Mike Harris  
Version: 0.3.0  
GitHub: https://github.com/GlacialDrift/image-review-tool  
---

# Image Review Tool (SQLite + Tkinter)

**Image Review Tool** is a lightweight, Python-based GUI for structured image review.  
It allows multiple reviewers to evaluate images in parallel, automatically logs results to an SQLite database, and supports repeatability testing through QC (duplicate) reviews.

Originally designed for manufacturing defect review, it’s general-purpose: any binary or categorical image classification task can use it. Reviewers can decide their own acceptance criteria (e.g., pass/fail, yes/no, or custom labels).

---

## Features

- Multi-user support via SQLite + WAL (safe over SMB/network drives)
- Configurable results, keybinds, and mouse actions through `config.ini`
- Optional QC duplication (assigns a subset of images for double review)
- Optional click-based annotation logging (stores normalized coordinates)
- Simple setup: one executable, one database file, one image root
- Extensible for any image labeling or inspection workflow

---

## Installation & Setup

### 1. Download the Application
Download the latest release (`ImageReview.zip`) from the [GitHub Releases page](https://github.com/GlacialDrift/image-review-tool/releases).

### 2. Extract and Configure
1. Extract the ZIP to a convenient folder.
2. Copy `config.example.ini` → rename it to `config.ini`.
3. Edit `config.ini`:
   - Set the database path:
     ```ini
     db_path=//Shared/Network/Drive/review.db
     ```
   - Set the image root directory:
     ```ini
     image_root=//Shared/Network/Drive/images
     ```
   - Ensure both live in the same parent folder for consistency.
4. (Optional) Adjust `[results]`, `[mouse]`, or `[image]` settings for your workflow.
5. Use UNC paths (`\\Server\Share\...`) when working over a network share.

**Tip:** Avoid drive letters (e.g., `Z:\`) unless running locally.  
SQLite performs best over SMB shares with **WAL mode**, which this app enables automatically.

---

## Running the App

Double-click `ImageReview.exe` (or run `python run_app.py` for development).

When launched:
- The first available batch of images is automatically assigned.
- Images are displayed one at a time.
- Decisions are recorded immediately in the database.

### Default Key & Mouse Bindings
- **Y**, **B** → mark as “yes” (observed)
- **N**, **G** → mark as “no” (not observed)
- **K** or **Space** → mark as “skip”
- **Left-click** → mark “yes” and record click location
- **Right-click** → mark “no”
- **Esc** → exit early and release any in-progress images

These bindings and behaviors are fully configurable in `config.ini`.

---

## Workflow

1. Each reviewer receives a random batch (default: 20 images).
2. ~10% of all images are duplicated for QC — two reviewers see the same image independently.
3. After each batch, the app prompts to continue or exit.
4. Press **Esc** or close the window to cancel early — unfinished images are released back to the pool.
5. All activity is logged immediately to the shared SQLite database.

---

## Database Management

### Creating the Database
Run:
```bash
python init_db.py
```

## Build
pyinstaller --onefile --noconsole --name ImageReview --paths . --add-data "schema.sql;." --add-data "config.example.ini;." run_app.py