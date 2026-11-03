"""文件仓落盘与索引。SQLite 只存元数据，文件本体按会话归档。"""

from __future__ import annotations

import re
import secrets
import shutil
import sqlite3
import time
from contextlib import closing
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

KINDS: dict[str, tuple[str, ...]] = {
    "word": (".docx", ".doc"),
    "excel": (".xlsx", ".xls"),
    "ppt": (".pptx", ".ppt"),
    "pdf": (".pdf",),
    "text": (".txt", ".log"),
    "markdown": (".md", ".markdown"),
    "code": (
        ".py", ".js", ".ts", ".json", ".yaml", ".yml", ".sh", ".sql",
        ".html", ".css", ".toml", ".ini",
    ),
    "csv": (".csv", ".tsv"),
    "video": (".mp4", ".mov", ".mkv", ".avi", ".webm"),
}

EXT_KIND = {ext: kind for kind, exts in KINDS.items() for ext in exts}
KIND_ORDER = list(KINDS)

SCHEMA = """
CREATE TABLE IF NOT EXISTS files (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    ext TEXT NOT NULL,
    kind TEXT NOT NULL,
    size INTEGER NOT NULL,
    session TEXT NOT NULL,
    sender TEXT NOT NULL DEFAULT '',
    note TEXT NOT NULL DEFAULT '',
    fingerprint TEXT NOT NULL DEFAULT '',
    current_version INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS versions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    file_id TEXT NOT NULL,
    version INTEGER NOT NULL,
    path TEXT NOT NULL,
    size INTEGER NOT NULL,
    note TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    UNIQUE (file_id, version)
);
CREATE INDEX IF NOT EXISTS idx_files_kind ON files (kind, updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_versions_file ON versions (file_id, version DESC);
"""


def kind_of(name: str) -> str | None:
    return EXT_KIND.get(Path(name).suffix.lower())


def human_size(num: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if num < 1024 or unit == "GB":
            return f"{num:.0f}{unit}" if unit == "B" else f"{num:.1f}{unit}"
        num /= 1024
    return f"{num:.1f}GB"


_BAD_CHARS = re.compile(r"[^\w\u4e00-\u9fff-]+")


def _safe(name: str) -> str:
    keep = _BAD_CHARS.sub("_", Path(name).stem).strip("_")
    return (keep or "file")[:60]


class FileStore:
    def __init__(self, root: Path, retention_days: int = 90, max_versions: int = 20):
        self.root = Path(root)
        self.files_dir = self.root / "files"
        self.versions_dir = self.root / "versions"
        self.temp_dir = self.root / "temp"
        for d in (self.files_dir, self.versions_dir, self.temp_dir):
            d.mkdir(parents=True, exist_ok=True)
        self.db_path = self.root / "index.db"
        self.retention_days = retention_days
        self.max_versions = max_versions
        with closing(self._conn()) as conn:
            conn.executescript(SCHEMA)

    # ── 基础设施 ──────────────────────────────────────────────
    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=10)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    @staticmethod
    def _now() -> str:
        return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    def _slot(self, file_id: str, session: str, name: str, ext: str) -> Path:
        folder = self.files_dir / _safe(session) / datetime.now().strftime("%Y-%m")
        folder.mkdir(parents=True, exist_ok=True)
        return folder / f"{_safe(name)}.{file_id}{ext}"

    def _write(self, target: Path, data: bytes | None, src: Path | None) -> int:
        target.parent.mkdir(parents=True, exist_ok=True)
        if src is not None:
            shutil.copyfile(src, target)
        else:
            target.write_bytes(data or b"")
        return target.stat().st_size

    # ── 写入 ─────────────────────────────────────────────────
    def add(
        self,
        name: str,
        session: str,
        data: bytes | None = None,
        src: Path | None = None,
        sender: str = "",
        note: str = "",
    ) -> dict[str, Any]:
        ext = Path(name).suffix.lower()
        kind = EXT_KIND.get(ext)
        if not kind:
            raise ValueError(f"不支持的文件类型：{ext or name}")
        file_id = secrets.token_hex(4)
        target = self._slot(file_id, session, name, ext)
        size = self._write(target, data, src)
        now = self._now()
        with closing(self._conn()) as conn, conn:
            conn.execute(
                "INSERT INTO files (id,name,ext,kind,size,session,sender,note,"
                "current_version,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (file_id, Path(name).name, ext, kind, size, session, sender, note,
                 1, now, now),
            )
            conn.execute(
                "INSERT INTO versions (file_id,version,path,size,note,created_at)"
                " VALUES (?,?,?,?,?,?)",
                (file_id, 1, str(target), size, note or "入库", now),
            )
        return self.get(file_id)

    def add_version(
        self,
        file_id: str,
        data: bytes | None = None,
        src: Path | None = None,
        note: str = "",
    ) -> dict[str, Any]:
        rec = self.get(file_id)
        if not rec:
            raise KeyError(file_id)
        now = self._now()
        new_ver = int(rec["current_version"]) + 1
        cur = Path(rec["path"])
        archive = self.versions_dir / file_id / f"v{rec['current_version']}{rec['ext']}"
        if cur.exists() and not archive.exists():
            archive.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(cur), str(archive))
            with closing(self._conn()) as conn, conn:
                conn.execute(
                    "UPDATE versions SET path=? WHERE file_id=? AND version=?",
                    (str(archive), file_id, rec["current_version"]),
                )
        size = self._write(cur, data, src)
        with closing(self._conn()) as conn, conn:
            conn.execute(
                "INSERT INTO versions (file_id,version,path,size,note,created_at)"
                " VALUES (?,?,?,?,?,?)",
                (file_id, new_ver, str(cur), size, note or "改写", now),
            )
            conn.execute(
                "UPDATE files SET size=?,current_version=?,updated_at=? WHERE id=?",
                (size, new_ver, now, file_id),
            )
        self._trim(file_id)
        return self.get(file_id)

    def _trim(self, file_id: str) -> None:
        if self.max_versions <= 0:
            return
        with closing(self._conn()) as conn:
            rows = conn.execute(
                "SELECT version,path FROM versions WHERE file_id=? ORDER BY version DESC",
                (file_id,),
            ).fetchall()
        for row in rows[self.max_versions:]:
            Path(row["path"]).unlink(missing_ok=True)
            with closing(self._conn()) as conn, conn:
                conn.execute(
                    "DELETE FROM versions WHERE file_id=? AND version=?",
                    (file_id, row["version"]),
                )

    # ── 查询 ─────────────────────────────────────────────────
    def get(self, file_id: str) -> dict[str, Any] | None:
        with closing(self._conn()) as conn:
            row = conn.execute(
                "SELECT f.*, v.path FROM files f JOIN versions v"
                " ON v.file_id=f.id AND v.version=f.current_version WHERE f.id=?",
                (file_id,),
            ).fetchone()
            if not row:
                row = conn.execute(
                    "SELECT *, '' AS path FROM files WHERE id=?", (file_id,)
                ).fetchone()
        return dict(row) if row else None

    def search(self, kind: str | None = None, query: str = "", limit: int = 500) -> list[dict]:
        sql = "SELECT * FROM files WHERE 1=1"
        args: list[Any] = []
        if kind:
            sql += " AND kind=?"
            args.append(kind)
        if query:
            sql += " AND (name LIKE ? OR note LIKE ?)"
            args += [f"%{query}%", f"%{query}%"]
        sql += " ORDER BY updated_at DESC LIMIT ?"
        args.append(limit)
        with closing(self._conn()) as conn:
            return [dict(r) for r in conn.execute(sql, args)]

    def versions(self, file_id: str) -> list[dict]:
        with closing(self._conn()) as conn:
            return [
                dict(r)
                for r in conn.execute(
                    "SELECT * FROM versions WHERE file_id=? ORDER BY version DESC",
                    (file_id,),
                )
            ]

    def counts(self) -> dict[str, int]:
        with closing(self._conn()) as conn:
            rows = conn.execute(
                "SELECT kind, COUNT(*) c FROM files GROUP BY kind"
            ).fetchall()
        out = {k: 0 for k in KIND_ORDER}
        for r in rows:
            out[r["kind"]] = r["c"]
        return out

    def stats(self) -> dict[str, Any]:
        with closing(self._conn()) as conn:
            row = conn.execute(
                "SELECT COUNT(*) n, COALESCE(SUM(size),0) s FROM files"
            ).fetchone()
        return {"files": row["n"], "bytes": row["s"], "counts": self.counts()}

    # ── 删除与清理 ───────────────────────────────────────────
    def delete(self, file_id: str) -> bool:
        rec = self.get(file_id)
        if not rec:
            return False
        for v in self.versions(file_id):
            Path(v["path"]).unlink(missing_ok=True)
        vdir = self.versions_dir / file_id
        if vdir.is_dir():
            shutil.rmtree(vdir, ignore_errors=True)
        Path(rec.get("path") or "").unlink(missing_ok=True)
        with closing(self._conn()) as conn, conn:
            conn.execute("DELETE FROM versions WHERE file_id=?", (file_id,))
            conn.execute("DELETE FROM files WHERE id=?", (file_id,))
        return True

    def purge(self) -> dict[str, int]:
        removed = expired = 0
        if self.retention_days > 0:
            cutoff = (datetime.now() - timedelta(days=self.retention_days)).strftime(
                "%Y-%m-%d %H:%M:%S"
            )
            with closing(self._conn()) as conn:
                stale = [
                    r["id"]
                    for r in conn.execute(
                        "SELECT id FROM files WHERE updated_at < ?", (cutoff,)
                    )
                ]
            for fid in stale:
                expired += int(self.delete(fid))
        for entry in self.temp_dir.glob("*"):
            try:
                if entry.is_file() and time.time() - entry.stat().st_mtime > 86400:
                    entry.unlink()
                    removed += 1
            except OSError:
                pass
        return {"expired": expired, "temp": removed}
