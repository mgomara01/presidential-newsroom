import os
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

source = Path(os.environ.get("DATABASE_PATH", "instance/newsroom.db"))
backup_dir = Path(os.environ.get("BACKUP_DIR", "backups"))
backup_dir.mkdir(parents=True, exist_ok=True)
target = backup_dir / f"newsroom-{datetime.now(UTC):%Y%m%d-%H%M%S}.db"
with sqlite3.connect(source) as src, sqlite3.connect(target) as dst:
    src.backup(dst)
print(target)
