from __future__ import annotations

import sqlite3
import tarfile
import tempfile
import unittest
import os
from pathlib import Path
from unittest import mock

from scripts import local_backup


class LocalBackupTests(unittest.TestCase):
    def test_creates_restorable_archive_and_rotates_old_files(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            data_dir = root / "data"
            backup_dir = root / "backups" / "local"
            data_dir.mkdir(parents=True)
            (root / "config.json").write_text('{"auth-key":"test"}\n', encoding="utf-8")
            connection = sqlite3.connect(data_dir / "accounts.db")
            try:
                connection.execute("CREATE TABLE sample (value TEXT)")
                connection.execute("INSERT INTO sample VALUES ('ok')")
                connection.commit()
            finally:
                connection.close()
            backup_dir.mkdir(parents=True)
            for index in range(3):
                (backup_dir / f"chatgpt2api-20200101-00000{index}.tar.gz").write_bytes(b"old")

            with (
                mock.patch.object(local_backup, "ROOT", root),
                mock.patch.object(local_backup, "DATA_DIR", data_dir),
                mock.patch.object(local_backup, "BACKUP_DIR", backup_dir),
                mock.patch.object(local_backup, "KEEP", 2),
            ):
                local_backup.main()

            archives = sorted(backup_dir.glob("chatgpt2api-*.tar.gz"))
            self.assertEqual(len(archives), 2)
            newest = archives[-1]
            if os.name == "posix":
                self.assertEqual(newest.stat().st_mode & 0o777, 0o600)
            with tarfile.open(newest, "r:gz") as archive:
                self.assertIn("accounts.db", archive.getnames())
                self.assertIn("config.json", archive.getnames())


if __name__ == "__main__":
    unittest.main()
