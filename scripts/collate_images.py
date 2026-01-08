import sqlite3
import shutil
from pathlib import Path

DB_PATH = r"\\MGROVEF12\Shared\RandD\Pharmaceutical Sciences Group\Hemoteq\p16 Image Review\review4.db"
DEST_DIR = Path(r"\\MGROVEF12\Shared\RandD\Pharmaceutical Sciences Group\Hemoteq\p16 Image Review\yes-images")  # single flat folder



def main():
    DEST_DIR.mkdir(parents=True, exist_ok=True)

    q = (
        """
            SELECT i."path"
            FROM images AS i
            JOIN reviews AS r ON r.image_id = i.image_id
            WHERE r.result = 'yes' LIMIT 10
                AND i."path" IS NOT NULL
                AND i."path" <> '';
        """
    )

    missing = []
    copied = 0

    with sqlite3.connect(DB_PATH) as conn:
        rows = conn.execute("""
            SELECT i."path"
            FROM images i
            JOIN reviews r ON r.image_id = i.image_id
            WHERE r.result = 'yes';
        """).fetchall()

    print(f"Found {len(rows)} images with result='yes'")

    for (path_str,) in rows:
        src = Path(path_str)
        if not src.exists():
            missing.append(path_str)
            continue

        dst = DEST_DIR / src.name  # flat folder by filename
        # Since filenames are unique, overwrites should not happen. Still, guard just in case:
        if dst.exists():
            raise FileExistsError(f"Destination file already exists: {dst}")

        shutil.copy2(src, dst)  # preserves timestamps/metadata
        copied += 1

        if copied % 10 == 0:
            print(f"Copied {copied}...")

    print(f"Copied {copied} files to: {DEST_DIR}")

    if missing:
        missing_log = DEST_DIR / "missing_files.txt"
        missing_log.write_text("\n".join(missing), encoding="utf-8")
        print(f"WARNING: {len(missing)} source files were missing. Logged to: {missing_log}")

if __name__ == "__main__":
    main()
