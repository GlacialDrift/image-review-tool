from app.config import load_config
from app.db import connect

"""Migration: Add UNIQUE constraint to images.sha256 column.

This migration recreates the images table with a UNIQUE constraint on sha256
while preserving all existing data and foreign key relationships.
"""
def migrate():
    cfg = load_config()
    con = connect(cfg["DB_PATH"])

    print("Starting migration: Adding UNIQUE constraint to images.sha256...")

    # Use executescript to run everything in one transaction
    con.executescript("""  
        PRAGMA foreign_keys=OFF;  
        BEGIN IMMEDIATE;  

        -- Create new images table with UNIQUE constraint on sha256  
        CREATE TABLE images_new (  
          image_id      INTEGER PRIMARY KEY,  
          path          TEXT UNIQUE NOT NULL,  
          device_id     TEXT NOT NULL,  
          variant       TEXT NOT NULL,  
          sha256        TEXT UNIQUE NOT NULL,  
          registered_at TEXT NOT NULL,  
          qc_flag       INTEGER NOT NULL DEFAULT 0  
        );  

        -- Copy all data from old table to new table  
        INSERT INTO images_new   
          (image_id, path, device_id, variant, sha256, registered_at, qc_flag)  
        SELECT image_id, path, device_id, variant, sha256, registered_at, qc_flag  
        FROM images;  

        -- Drop old table  
        DROP TABLE images;  

        -- Rename new table to original name  
        ALTER TABLE images_new RENAME TO images;  

        COMMIT;  
        PRAGMA foreign_keys=ON;  
    """)

    print("Migration completed successfully!")
    print("The images table now has a UNIQUE constraint on sha256.")

    con.close()

def verify_migration():
    cfg = load_config()
    con = connect(cfg["DB_PATH"])

    print("=== Migration Verification ===\n")

    # 1. Check schema
    schema = con.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='images'"
    ).fetchone()[0]
    has_unique = "sha256" in schema and "UNIQUE" in schema
    print(f"1. UNIQUE constraint on sha256: {'✓ FOUND' if has_unique else '✗ MISSING'}")

    # 2. Check foreign keys
    fk_violations = con.execute("PRAGMA foreign_key_check;").fetchall()
    print(f"2. Foreign key violations: {len(fk_violations)} {'✓ NONE' if len(fk_violations) == 0 else '✗ FOUND'}")

    # 3. Check orphaned reviews
    orphaned_reviews = con.execute("""  
        SELECT COUNT(*) FROM reviews r  
        LEFT JOIN images i ON r.image_id = i.image_id  
        WHERE i.image_id IS NULL  
    """).fetchone()[0]
    print(f"3. Orphaned reviews: {orphaned_reviews} {'✓ NONE' if orphaned_reviews == 0 else '✗ FOUND'}")

    # 4. Check orphaned annotations
    orphaned_annotations = con.execute("""  
        SELECT COUNT(*) FROM annotations a  
        LEFT JOIN reviews r ON a.review_id = r.review_id  
        WHERE r.review_id IS NULL  
    """).fetchone()[0]
    print(f"4. Orphaned annotations: {orphaned_annotations} {'✓ NONE' if orphaned_annotations == 0 else '✗ FOUND'}")

    # 5. Count totals
    image_count = con.execute("SELECT COUNT(*) FROM images").fetchone()[0]
    review_count = con.execute("SELECT COUNT(*) FROM reviews").fetchone()[0]
    annotation_count = con.execute("SELECT COUNT(*) FROM annotations").fetchone()[0]

    print(f"\n=== Data Counts ===")
    print(f"Images: {image_count}")
    print(f"Reviews: {review_count}")
    print(f"Annotations: {annotation_count}")

    if has_unique and len(fk_violations) == 0 and orphaned_reviews == 0 and orphaned_annotations == 0:
        print("\n✓ Migration successful! All checks passed.")
    else:
        print("\n✗ Migration issues detected. Review output above.")

    con.close()


if __name__ == "__main__":
    migrate()
    verify_migration()