"""Create a consistent backup of the SQLite database.

Uses SQLite's online backup API, which is safe even if the application is
running (unlike copying db.sqlite3 with File Explorer). The backup is then
verified with PRAGMA integrity_check.

    python scripts/backup_db.py
    python scripts/backup_db.py --db path\\to\\db.sqlite3 --out D:\\tpi-backups

Backups contain real production data. Keep them OUT of the Git repository
(the default 'backups' folder is listed in .gitignore).
"""

import argparse
import os
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def default_db_path():
    return Path(os.environ.get("DJANGO_DB_PATH", PROJECT_ROOT / "db.sqlite3"))


def backup(db_path, out_dir):
    db_path = Path(db_path)
    if not db_path.is_file():
        raise SystemExit(f"Database not found: {db_path}")
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    target = out_dir / f"{db_path.stem}_{stamp}.sqlite3"
    if target.exists():
        raise SystemExit(f"Refusing to overwrite existing backup: {target}")

    source = sqlite3.connect(f"{db_path.resolve().as_uri()}?mode=ro", uri=True)
    destination = sqlite3.connect(str(target))
    try:
        source.backup(destination)
    finally:
        destination.close()
        source.close()

    check = sqlite3.connect(str(target))
    try:
        result = check.execute("PRAGMA integrity_check").fetchone()[0]
    finally:
        check.close()
    if result != "ok":
        target.unlink()
        raise SystemExit(f"Backup failed its integrity check ({result}); it was deleted.")
    return target


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--db", default=str(default_db_path()), help="database file")
    parser.add_argument("--out", default=str(PROJECT_ROOT / "backups"), help="backup folder")
    args = parser.parse_args(argv)
    target = backup(args.db, args.out)
    print(f"Backup created and verified: {target}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
