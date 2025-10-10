# Image Review Tool (SQLite + Tk)

- Configure `config.ini` from `config.example.ini` (UNC paths).
- Run `python scripts/init_db.py` to index images.
- Run `python -m app.main` to review (Y/N keys).
- Export results: `python scripts/export_csv.py`.

SQLite lives on the SMB share; WAL mode enabled for multi-user safety.
