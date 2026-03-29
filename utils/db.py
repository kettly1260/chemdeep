import sqlite3
import json
import uuid
from pathlib import Path
from datetime import datetime, timezone
from typing import Any

def now_iso():
    return datetime.now(timezone.utc).isoformat()


class DB:
    def __init__(self, path: Path = Path("chemdeep.db")):
        self.path = path
        self._conn = sqlite3.connect(self.path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._init()

    def _init(self):
        self._conn.executescript("""
            CREATE TABLE IF NOT EXISTS kv (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS jobs (
                job_id TEXT PRIMARY KEY,
                created_at TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'queued',
                goal TEXT NOT NULL,
                args_json TEXT NOT NULL,
                progress REAL DEFAULT 0.0,
                message TEXT,
                cancel_requested INTEGER DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS papers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                job_id TEXT NOT NULL,
                doi TEXT,
                title TEXT,
                year TEXT,
                source TEXT,
                ut TEXT,
                status TEXT DEFAULT 'imported',
                landing_url TEXT,
                raw_html_path TEXT,
                clean_md_path TEXT,
                synthesis_missing INTEGER,
                si_json TEXT,
                fetch_error TEXT
            );
            CREATE TABLE IF NOT EXISTS research_requests (
                request_id TEXT PRIMARY KEY,
                chat_id INTEGER NOT NULL,
                user_query TEXT NOT NULL,
                ai_strategy TEXT,
                created_at TEXT NOT NULL,
                status TEXT DEFAULT 'pending'
            );
            -- 添加 DOI 索引以优化查询
            CREATE INDEX IF NOT EXISTS idx_papers_doi ON papers(doi);
            CREATE INDEX IF NOT EXISTS idx_papers_status ON papers(status);
        """)
        self._conn.commit()
    
    def is_doi_fetched(self, doi: str) -> bool:
        """检查某个 DOI 是否已在任意任务中成功抓取"""
        if not doi:
            return False
        row = self._conn.execute(
            "SELECT id FROM papers WHERE doi=? AND status='fetched' LIMIT 1",
            (doi.strip().lower(),)
        ).fetchone()
        return row is not None
    
    def get_fetched_dois(self) -> set[str]:
        """获取所有已成功抓取的 DOI 集合"""
        rows = self._conn.execute(
            "SELECT DISTINCT LOWER(doi) as doi FROM papers WHERE status='fetched' AND doi IS NOT NULL"
        ).fetchall()
        return {row["doi"] for row in rows}
    
    def get_paper_by_doi(self, doi: str) -> sqlite3.Row | None:
        """根据 DOI 查找已抓取的论文记录"""
        if not doi:
            return None
        return self._conn.execute(
            "SELECT * FROM papers WHERE doi=? AND status='fetched' ORDER BY id DESC LIMIT 1",
            (doi.strip().lower(),)
        ).fetchone()

    def kv_get(self, key: str, default: str | None = None) -> str | None:
        row = self._conn.execute("SELECT value FROM kv WHERE key=?", (key,)).fetchone()
        if not row:
            return default
        return row["value"]

    def kv_get_int(self, key: str, default: int | None = None) -> int | None:
        val = self.kv_get(key)
        if val is None:
            return default
        try:
            return int(val)
        except ValueError:
            return default

    def kv_set(self, key: str, value: str | None) -> None:
        if value is None:
            self.kv_delete(key)
            return
        self._conn.execute(
            "INSERT INTO kv(key, value) VALUES(?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, value),
        )
        self._conn.commit()
    
    def kv_delete(self, key: str) -> None:
        self._conn.execute("DELETE FROM kv WHERE key=?", (key,))
        self._conn.commit()

    def create_job(self, goal: str, args: dict[str, Any]) -> str:
        job_id = uuid.uuid4().hex[:12]
        ts = now_iso()
        self._conn.execute(
            "INSERT INTO jobs(job_id, created_at, status, goal, args_json) VALUES(?, ?, 'queued', ?, ?)",
            (job_id, ts, goal, json.dumps(args, ensure_ascii=False)),
        )
        self._conn.commit()
        return job_id

    def list_jobs(self, limit: int = 5) -> list[sqlite3.Row]:
        return self._conn.execute(
            "SELECT * FROM jobs ORDER BY created_at DESC LIMIT ?", (limit,)
        ).fetchall()

    def update_job_status(self, job_id: str, status: str, message: str = None) -> None:
        """更新任务状态"""
        if message:
            self._conn.execute(
                "UPDATE jobs SET status=?, message=? WHERE job_id=?", 
                (status, message, job_id)
            )
        else:
            self._conn.execute(
                "UPDATE jobs SET status=? WHERE job_id=?", 
                (status, job_id)
            )
        self._conn.commit()

    def request_cancel(self, job_id: str) -> None:
        self._conn.execute("UPDATE jobs SET cancel_requested=1 WHERE job_id=?", (job_id,))
        self._conn.commit()

    def cancel_requested(self, job_id: str) -> bool:
        row = self._conn.execute("SELECT cancel_requested FROM jobs WHERE job_id=?", (job_id,)).fetchone()
        return bool(row and row["cancel_requested"])

    def list_papers(self, job_id: str) -> list[sqlite3.Row]:
        return self._conn.execute("SELECT * FROM papers WHERE job_id=? ORDER BY id", (job_id,)).fetchall()

    def update_paper_fetch(
        self,
        paper_row_id: int,
        *,
        status: str,
        landing_url: str | None = None,
        raw_html_path: str | None = None,
        clean_md_path: str | None = None,
        synthesis_missing: int | None = None,
        si_json: str | None = None,
        fetch_error: str | None = None,
    ) -> None:
        parts = ["status=?"]
        vals: list[Any] = [status]
        if landing_url is not None:
            parts.append("landing_url=?")
            vals.append(landing_url)
        if raw_html_path is not None:
            parts.append("raw_html_path=?")
            vals.append(raw_html_path)
        if clean_md_path is not None:
            parts.append("clean_md_path=?")
            vals.append(clean_md_path)
        if synthesis_missing is not None:
            parts.append("synthesis_missing=?")
            vals.append(synthesis_missing)
        if si_json is not None:
            parts.append("si_json=?")
            vals.append(si_json)
        if fetch_error is not None:
            parts.append("fetch_error=?")
            vals.append(fetch_error)
        vals.append(paper_row_id)
        sql = f"UPDATE papers SET {', '.join(parts)} WHERE id=?"
        self._conn.execute(sql, tuple(vals))
        self._conn.commit()

    def create_research_request(self, chat_id: int, user_query: str) -> str:
        request_id = f"req_{uuid.uuid4().hex[:8]}"
        self._conn.execute(
            "INSERT INTO research_requests (request_id, chat_id, user_query, created_at) VALUES (?, ?, ?, ?)",
            (request_id, chat_id, user_query, now_iso())
        )
        self._conn.commit()
        return request_id

    def update_request_strategy(self, request_id: str, strategy: dict) -> None:
        self._conn.execute(
            "UPDATE research_requests SET ai_strategy=?, status='strategy_ready' WHERE request_id=?",
            (json.dumps(strategy, ensure_ascii=False), request_id)
        )
        self._conn.commit()