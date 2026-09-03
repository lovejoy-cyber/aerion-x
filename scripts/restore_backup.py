"""Offline restore — run with the backend NOT running. Restoring into a live
DB file while the server holds an open connection would corrupt it, so this
is a standalone script rather than an API endpoint (see backend/backup.py).

Usage:
    python -m scripts.restore_backup data/backups/aerionx_backup_1234567890.sqlite3
"""
import sys

from backend import backup


def main():
    if len(sys.argv) != 2:
        print("Usage: python -m scripts.restore_backup <backup_file>")
        sys.exit(1)
    backup_path = sys.argv[1]
    target = "data/db/aerionx.sqlite3"
    print(f"Restoring {backup_path} -> {target}")
    print("Make sure the backend is NOT running before continuing (Ctrl+C to abort, Enter to proceed)")
    input()
    backup.restore_backup(backup_path, target)
    print("Restore complete.")


if __name__ == "__main__":
    main()
