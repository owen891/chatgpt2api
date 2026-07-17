from __future__ import annotations

import os
import shutil
import sqlite3
import tarfile
import tempfile
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(os.environ.get("CHATGPT2API_ROOT", "/root/o-chatgpt2api")).resolve()
DATA_DIR = ROOT / "data"
BACKUP_DIR = ROOT / "backups" / "local"
KEEP = max(1, int(os.environ.get("CHATGPT2API_BACKUP_KEEP", "10")))


def _copy_sqlite(source: Path, destination: Path) -> None:
    source_conn = sqlite3.connect(f"file:{source}?mode=ro", uri=True)
    destination_conn = sqlite3.connect(destination)
    try:
        source_conn.backup(destination_conn)
    finally:
        destination_conn.close()
        source_conn.close()


def main() -> None:
    database = DATA_DIR / "accounts.db"
    config = ROOT / "config.json"
    if not database.is_file() or not config.is_file():
        raise SystemExit("accounts.db and config.json are required")

    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    os.chmod(BACKUP_DIR, 0o700)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    archive = BACKUP_DIR / f"chatgpt2api-{stamp}.tar.gz"

    with tempfile.TemporaryDirectory(dir=BACKUP_DIR) as temp_dir:
        staging = Path(temp_dir)
        _copy_sqlite(database, staging / "accounts.db")
        shutil.copy2(config, staging / "config.json")
        for name in ("image_tasks.json", "image_index.json", "auth_keys.json"):
            path = DATA_DIR / name
            if path.is_file():
                shutil.copy2(path, staging / name)
        with tarfile.open(archive, "w:gz") as output:
            for path in sorted(staging.iterdir()):
                output.add(path, arcname=path.name)

    os.chmod(archive, 0o600)
    archives = sorted(BACKUP_DIR.glob("chatgpt2api-*.tar.gz"), key=lambda path: path.name, reverse=True)
    for old_archive in archives[KEEP:]:
        old_archive.unlink()


if __name__ == "__main__":
    main()
