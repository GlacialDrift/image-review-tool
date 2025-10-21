---
Author: Mike Harris  
Version: 0.3.1  
GitHub: https://github.com/GlacialDrift/image-review-tool  
---

# Image Review Tool (SQLite + Tkinter)

This ImageReview Tool is a lightweight, Python-based GUI for image review. It allows multiple reviewers to evaluate 
images in parallel, automatically logs results to an SQLite database, and supports (optional) repeatability testing 
through duplicate "QC" reviews.

Originally designed for manufacturing defect review, it’s general-purpose: any binary or categorical image 
classification task can use it. Reviewers can decide their own acceptance criteria (e.g., pass/fail, yes/no, or 
custom labels) by modifying the included `config.ini` file.


## Features

- Multi-user support
- Configurable results, keybinds, and mouse actions through `config.ini`
- Optional QC duplication (assigns a subset of images for double review)
- Optional click-based annotation (stores normalized coordinates of click location on the image)
- Simple setup: one executable, one database file, one image root
- Extensible for any image labeling or inspection workflow


## Installation & Setup

### 1. Download the Application
Download the latest release (`ImageReview.zip`) from the [GitHub Releases page](https://github.com/GlacialDrift/image-review-tool/releases).

### 2. Extract and Configure
1. Extract the ZIP to a convenient folder.
2. Copy `config.example.ini` → rename it to `config.ini`.
3. Edit `config.ini`:
   - Set the database path to the correct network drive or local folder:
     ```ini
     db_path=//Example/Path/To/Folder/review.db
     ```
   - Set the image root directory. Place these images in the same directory:
     ```ini
     image_root=//Example/Path/To/Folder/images
     ```
   - Recommended both live in the same parent folder for consistency, although not strictly necessary.
   - Recommend using a network drive to prevent simultaneous database writing issues.
4. (Optional) Adjust `[results]`, `[mouse]`, or `[image]` settings for your workflow.
5. Use UNC paths (`//Server/Share/...`) when working over a network share.
   - From experience, using forward slashes `/` have provided more robust path names.

**Tip:** Avoid drive letters (e.g., `Z:\`) unless running locally.  

SQLite performs best over SMB shares with **WAL mode**, which this app enables automatically. If you do not know about 
SMB or WAL mode, simply put everything on a shared network drive


## Running the App

Double-click `ImageReview.exe` (or run `python run_app.py` for development).

When launched:
- The first available batch of images is automatically assigned, selecting random images from the entire available set.
- Images for each batch are displayed one at a time in randomized order.
- Decisions are recorded immediately in the database.

### Default Key & Mouse Bindings
- **Y**, **B** → mark as “yes” (observed)
- **N**, **G** → mark as “no” (not observed)
- **K** or **Space** → mark as “skip”
- **Left-click** → mark “yes” and record click location
- **Right-click** → mark “no”
- **Esc** → exit early and release any in-progress images

These bindings and behaviors are fully configurable in `config.ini`.


## Workflow

1. Each reviewer receives a random batch (default: 20 images) from the pool of unreviewed images.
2. By default, ~10% of all images are duplicated for QC — two reviewers see the same image independently.
3. After each batch, the app prompts to continue or exit.
4. Press **Esc** or close the window to cancel early — unfinished images are released back to the pool.
5. All activity is logged immediately to the shared SQLite database.


## Database Management

### Creating the Database
Run:
```bash
python init_db.py
```

## Build
pyinstaller --onefile --noconsole --name ImageReview --paths . --add-data "schema.sql;." --add-data "config.example.ini;." run_app.py