"""SQLite backup/restore using the real sqlite3 online backup API (not a naive
file copy — this is safe to run against a live, open connection because
sqlite3's `backup()` takes its own consistent snapshot, unlike `shutil.copy`
which can capture a half-written page if a write happens mid-copy).
"""
from __future__ import annotations

import shutil
import sqlite3
import time
from pathlib import Path

BACKUP_DIR = Path("data/backups")


def create_backup(conn: sqlite3.Connection, backup_dir: str | Path = BACKUP_DIR) -> str:
    backup_dir = Path(backup_dir)
    backup_dir.mkdir(parents=True, exist_ok=True)
    backup_path = backup_dir / f"aerionx_backup_{int(time.time())}.sqlite3"
    dest = sqlite3.connect(str(backup_path))
    with dest:
        conn.backup(dest)
    dest.close()
    return str(backup_path)


def restore_backup(backup_path: str, target_db_path: str) -> None:
    """Restores by copying the backup file over the target path. The caller
    is responsible for closing any existing connection to target_db_path
    first — restoring into a path with an open connection would corrupt it."""
    if not Path(backup_path).exists():
        raise FileNotFoundError(f"Backup file not found: {backup_path}")
    shutil.copy2(backup_path, target_db_path)


def list_backups(backup_dir: str | Path = BACKUP_DIR) -> list[dict]:
    backup_dir = Path(backup_dir)
    if not backup_dir.exists():
        return []
    return sorted(
        [{"path": str(p), "size_bytes": p.stat().st_size, "created_at": p.stat().st_mtime}
         for p in backup_dir.glob("aerionx_backup_*.sqlite3")],
        key=lambda b: -b["created_at"],
    )
