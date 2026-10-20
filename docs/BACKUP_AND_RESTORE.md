# Backup and restore (SQLite)

The database is a single file, `db.sqlite3` in the project folder (or the path
in `DJANGO_DB_PATH`). It holds your real production data: treat it as
confidential and never commit it (it is in `.gitignore`).

**Do not back up by copying `db.sqlite3` in File Explorer while the application
is running** - a write in progress can give an inconsistent copy. Use the
scripts, which use SQLite's online backup API.

## Create a backup

```
cd textile-production-intelligence
.venv\Scripts\activate
python scripts\backup_db.py
```

This writes `backups\db_<date>_<time>.sqlite3` and verifies it with
`PRAGMA integrity_check`. Use `--out D:\path` to choose another folder (for
example an external drive). Keep backups outside the Git repository.

## Restore

1. Close the application (stop the `runserver` window).
2. Preview: `python scripts\restore_db.py backups\db_<date>_<time>.sqlite3`
   (without `--yes` it changes nothing).
3. Restore: `python scripts\restore_db.py backups\db_<date>_<time>.sqlite3 --yes`

The script first saves the current database as `backups\pre_restore_<time>.sqlite3`,
checks the backup's integrity, restores, re-checks, and prints row counts per
table so you can confirm the records are back.
4. Start the application and open Orders / Production Records to confirm.

A backup is only proven restorable once you have restored it at least once
(try it on a copy, e.g. with `--db` pointing at a scratch file).

## Tested

`backup_db.py` and `restore_db.py` were exercised against a scratch SQLite
database (backup, refusal without `--yes`, restore, row counts, missing-file
error). They have not yet been run on Windows or against the real application
database.
