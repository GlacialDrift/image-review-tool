---
Author: Mike Harris  
Version: 1.0.0
GitHub: https://github.com/GlacialDrift/image-review-tool  
---

# Image Review Tool (SQLite + Tkinter)

This ImageReview Tool is a lightweight, Python-based GUI for image review. It allows multiple reviewers to evaluate 
images in parallel, automatically logs results to an SQLite database, and supports (optional) repeatability testing 
through duplicate "QC" reviews.

Originally designed for manufacturing defect review, it’s general-purpose: any binary or categorical image 
classification task can use it. Reviewers can decide their own acceptance criteria (e.g., pass/fail, yes/no, or 
custom labels) by modifying the included `config.ini` file.

v2.0 introduces powerful device-level automation (for multiple review images per device), variant-priority review, 
and auto-skip rules that reduce manual review time by 50-70% in real production settings.


## Features

### Device-Aware Review (New in v2.0.0)
- Images are grouped by an 11-digit device_id extracted from filenames. The reviewer’s decisions update both:
  - individual image reviews 
  - the device-level outcome
- Images are automatically reviewed in ascending variant order (e.g., `000` → `001` → `002` →...). This ensures the most informative images for each device are seen first.
- The tool intelligently skips images that no longer require review:
  - **YES Rule:**
    - If any image is marked yes, all remaining images for that device are auto-skipped. 
    - Device is finalized as yes. 
  - **Repeated–SKIP Rule:**
    - If the last three decisions for a device follow: `no → skip → skip` then the remaining images are auto-skipped 
    - Device is finalized as no. 
  - **Exhaustion Rule:**
    - If all images are reviewed and none were “yes,” the device is auto-finalized as no.
- Images are uniquely identified by their content hash. Duplicate files — even in different folders — are added only once.

### Core Features (from v1.0.0)
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

## Database Management

### Schema Overview
| Table         | Purpose                                               |
| ------------- | ----------------------------------------------------- |
| `images`      | one row per unique (SHA256) image                     |
| `reviews`     | one row per review task (QC images generate two rows) |
| `annotations` | optional click-location data                          |
| `devices`     | one row per device summarizing the final result       |

### Creating the Database
Run:
```bash
python init_db.py
```
### Functionality

This will:
- create tables if missing
- scan `image_root` for images
- compute `SHA256` for the *content* of each image
- insert new images only
- see corresponding review rows
- ensure every device has a unique row in `devices` table

The database will be generated at the location specified in the `config.ini` settings. 

## Running the App

Double-click `ImageReview.exe` (or run `python run_app.py` for development).

When launched:
- The first available batch is automatically assigned using variant-priority ordering: lower-numbered variants (e.g., 000) are reviewed first. Randomization only occurs within the same variant number.
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

### Workflow

#### Batch Assignment
1. Batches (default 20 images) are assigned using `variant`-priority ordering (the `variant` is the numerical suffix to an image file, e.g. `_000` or `_001`)
2. All `000` images are reviewed first, then `001`, then `002`, etc.

#### Device-Level Automation
3. After each decision, the system evaluates the device-level state:
    A. The **YES** Rule triggers if the image was marked `yes`. The entire device is marked `yes` and all remaining images for that device are marked as `skip`
    B. The **Repeated-Skip** Rule triggers if two `skips` follow a `no` decision for a single device, indicating with high likelihood that the unit has no scrap

#### General Workflow
1. Each reviewer receives a random batch from the pool of unreviewed images (after accounting for variant priority)
2. By default, ~10% of all images are duplicated for QC (configurable in `config.ini`) — two reviewers see the same image independently.
3. After each batch is completed, the app prompts to continue or exit.
4. Press **Esc** or close the window to cancel early — unfinished images are released back to the pool without any finalized review.
5. All activity is logged immediately to the shared SQLite database.

## Annotations and Database Export

### Image Annotations

Running the `draw_rings.py` script will generate annotated output images for all images that have spatial coordinates
associated with the review. If an image was clicked on to mark the spatial location of some feature, the script will 
open that image, draw a semi-transparent yellow ring centered on that location, and save the result as a copy to the 
output folder specified in `config.ini`.

### CSV Export

Running the `export_csv.py` script will create a CSV output of all reviewed images in the database and save the CSV to 
the location specified in `config.ini`. The CSV contains 11 columns that specifies all information relevant to the 
review of a given image:
1. `device_id` - the unique device (or image) identifier
2. `variant` - whether the image reviewed was a `000` or `001` image variant
3. `review id` - primary key of the review
4. `image id` - key used to link to the images table in the database
5. `path` - full filesystem path to the original image (at the time of review)
6. `user` - the user ID of the reviewer
7. `review batch` - UUID of the batch of images reviewed together
8. `timestamp` - the time at which the review was performed
9. `Result` - the result of the image review
10. `ImageReview_version` - the version of this program at the time of the image review
11. `QC` - a flag indicating whether the review was a quality control duplicate

## Adding New Images

New images can be added to the image_root folder at any point. Make sure the images follow the appropriate file naming
convention. After adding images to the folder, simply re-run `python init_db.py` to load the images into the database
for review. This will create new database entries for each of the **new** images in the image_root folder based on
the parameters in `config.ini` and will not affect any existing images/database entries. 

New images are defined as files that have unique file contents. The SHA256 digest of each file is used as a UUID for 
file's contents. This ensures that if the same file exists in two different sub-directories, only a single copy of
that file is added to the database for review. 

Re-running either the `export_csv.py` or `draw_rings.py` scripts will perform the same actions as before, overwriting 
any existing output (image or csv). 

## Building an Executable
pyinstaller --onefile --noconsole --name ImageReview --paths . --add-data "schema.sql;." --add-data "config.example.ini;." run_app.py