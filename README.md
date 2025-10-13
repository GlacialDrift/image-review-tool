---
Author: Mike Harris
Version: 0.1.0
Github: https://github.com/GlacialDrift/image-review-tool
---
# Image Review Tool (SQLite + Tk)

This Python-based tool can be used to review images and log the results to a database. It is set up to have
multiple users perform review simultaneously. 10% of all images to be reviewed have a duplicate review, ensuring
that two reviewers have performed review. This allows for evaluation of consistency between reviewers. 

This tool can in principle be used for review of any image set when looking for a specific feature within the images.
It was originally intended for review of scrapped manufacturing parts, but nothing within the tool specifies the feature
being reviewed. Therefore, it is up to the user(s) to define acceptance criteria for the images (e.g. pass/fail, yes/no).

## REVIEW App Download and Use Instructions

1. Download the latest release of the `zip` file on [github](https://github.com/GlacialDrift/image-review-tool/releases).
2. Extract the zip file to a known location
3. Create a copy of the `config.example.ini` file
4. Rename the copy to `config.ini`
5. In the `config.ini` file, update the paths for `db_path` and `image_root
    - **For users working specifically with Mike Harris, contact Mike Harris for appropriate file paths**
    - the `db_path` path should point to a `review.db` file
    - the `image_root` path should point to a `\images` directory
    - Note that due to python parsing, all `\` in a file path must be replaced with `\\`
    - the `review.db` file and `\images` directory should live in the same parent directory
    - Spaces are allowed in the file directories, but quotation marks **should not** be included
    - Paths should be UNC paths (e.g. `\\Shared\Network\Drive\`) and should not include drive letters (e.g. `Z:\`) unless all analysis will be performed on the local machine
    - It is highly recommended that the database live on a SMB share drive to ensure appropriate file locking with the SQLite database
6. Double-click the `.exe` to start
7. Use `y` and `n` keys on the keyboard for "yes" and "no" logging
8. QC images are automatically assigned for repeatability testing

## Database Setup and Export

To create the database for images to be reviewed, download the source code of this repository and run the `init_db.py` file.
Be sure to update the RegEx pattern to match the correct filenames and be sure to update the `db_path` and `image_root` path 
of within your `config.ini` file. 

To export the database after review of images, download the source code of this repository and run the `export_csv.py` file.
This will generate a csv file within the python project structure that can be further utilized.

SQLite lives on the SMB share; WAL mode enabled for multi-user safety.
