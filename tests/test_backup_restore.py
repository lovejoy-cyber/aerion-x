"""Real backup/restore test in a disposable tempdir: CREATE DATA -> BACKUP ->
DESTROY the live database -> RESTORE -> VERIFY the data survived. Every step
uses the actual sqlite3 backup API, not a mock.
"""
import os
import tempfile

from backend import backup, db, repositories
from core.assets.domain import Asset, AssetType


def test_backup_and_restore_round_trip_survives_database_destruction():
    with tempfile.TemporaryDirectory() as tmp:
        db_path = os.path.join(tmp, "aerionx.sqlite3")
        backup_dir = os.path.join(tmp, "backups")

        conn = db.get_connection(db_path)
        db.init_db(conn)
        repositories.save_asset(conn, Asset(asset_id="BACKUP_TEST_1", asset_type=AssetType.AIRCRAFT, name="Backup Test Aircraft"))

        backup_path = backup.create_backup(conn, backup_dir=backup_dir)
        assert os.path.exists(backup_path)
        assert os.path.getsize(backup_path) > 0

        conn.close()
        os.remove(db_path)  # simulate real database loss
        assert not os.path.exists(db_path)

        backup.restore_backup(backup_path, db_path)
        assert os.path.exists(db_path)

        restored_conn = db.get_connection(db_path)
        restored_asset = repositories.get_asset(restored_conn, "BACKUP_TEST_1")
        assert restored_asset is not None
        assert restored_asset["name"] == "Backup Test Aircraft"
        restored_conn.close()


def test_list_backups_reports_real_files():
    with tempfile.TemporaryDirectory() as tmp:
        db_path = os.path.join(tmp, "aerionx.sqlite3")
        backup_dir = os.path.join(tmp, "backups")
        conn = db.get_connection(db_path)
        db.init_db(conn)

        assert backup.list_backups(backup_dir) == []

        path1 = backup.create_backup(conn, backup_dir=backup_dir)
        backups = backup.list_backups(backup_dir)
        assert len(backups) == 1
        assert backups[0]["path"] == path1
        assert backups[0]["size_bytes"] > 0
        conn.close()


def test_restore_raises_for_missing_backup_file():
    with tempfile.TemporaryDirectory() as tmp:
        try:
            backup.restore_backup(os.path.join(tmp, "does_not_exist.sqlite3"), os.path.join(tmp, "target.sqlite3"))
            assert False, "expected FileNotFoundError"
        except FileNotFoundError:
            pass
