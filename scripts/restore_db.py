"""Restore the SQLite database from a backup made by backup_db.py.

STOP the application (close the run window) before restoring.

    python scripts/restore_db.py backups\\db_20260101_120000.sqlite3 --yes

The current database is first saved to the backups folder as
'pre_restore_<time>.sqlite3', the chosen backup is integrity-checked, and the
restored database is verified afterwards. Nothing happens without --yes.
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


def _integrity(path):
    conn = sqlite3.connect(str(path))
    try:
        return conn.execute("PRAGMA integrity_check").fetchone()[0]
    finally:
        conn.close()


def _table_counts(path):
    conn = sqlite3.connect(str(path))
    try:
        tables = [
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'production_%'"
            )
        ]
        return {t: conn.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0] for t in tables}
    finally:
        conn.close()


def restore(backup_path, db_path, backups_dir, confirmed):
    backup_path = Path(backup_path)
    db_path = Path(db_path)
    if not backup_path.is_file():
        raise SystemExit(f"Backup file not found: {backup_path}")
    if _integrity(backup_path) != "ok":
        raise SystemExit("The chosen backup failed its integrity check; nothing was changed.")
    if not confirmed:
        raise SystemExit(
            f"Dry run: would replace {db_path} with {backup_path}. "
            "Stop the application and re-run with --yes to proceed."
        )
    backups_dir = Path(backups_dir)
    backups_dir.mkdir(parents=True, exist_ok=True)
    safety = None
    if db_path.is_file():
        safety = backups_dir / f"pre_restore_{datetime.now().strftime('%Y%m%d_%H%M%S')}.sqlite3"
        src = sqlite3.connect(str(db_path))
        dst = sqlite3.connect(str(safety))
        try:
            src.backup(dst)
        finally:
            dst.close()
            src.close()
    source = sqlite3.connect(str(backup_path))
    destination = sqlite3.connect(str(db_path))
    try:
        source.backup(destination)
    finally:
        destination.close()
        source.close()
    if _integrity(db_path) != "ok":
        raise SystemExit(f"Restored database failed its integrity check. Previous copy: {safety}")
    return safety, _table_counts(db_path)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("backup", help="backup file to restore")
    parser.add_argument("--db", default=str(default_db_path()), help="database file to replace")
    parser.add_argument("--backups-dir", default=str(PROJECT_ROOT / "backups"))
    parser.add_argument("--yes", action="store_true", help="confirm the restore")
    args = parser.parse_args(argv)
    safety, counts = restore(args.backup, args.db, args.backups_dir, args.yes)
    if safety:
        print(f"Previous database saved to: {safety}")
    print("Restore complete. Row counts:")
    for table, n in sorted(counts.items()):
        print(f"  {table}: {n}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
