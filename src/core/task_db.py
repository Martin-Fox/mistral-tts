import sqlite3
import time
import os
import threading
from pathlib import Path
from typing import Optional, List, Dict, Any

class TaskDatabase:
    def __init__(self, db_path: Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path), timeout=30.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON;")
        return conn

    def _init_db(self):
        with self._lock:
            conn = self._get_connection()
            try:
                with conn:
                    # Create tasks table
                    conn.execute("""
                        CREATE TABLE IF NOT EXISTS tasks (
                            id TEXT PRIMARY KEY,
                            percentage INTEGER DEFAULT 0,
                            status TEXT DEFAULT 'Pending',
                            completed INTEGER DEFAULT 0,
                            audio_file TEXT,
                            error TEXT,
                            created_at REAL NOT NULL
                        )
                    """)
                    # Create task_logs table
                    conn.execute("""
                        CREATE TABLE IF NOT EXISTS task_logs (
                            id INTEGER PRIMARY KEY AUTOINCREMENT,
                            task_id TEXT NOT NULL,
                            message TEXT NOT NULL,
                            created_at REAL NOT NULL,
                            FOREIGN KEY(task_id) REFERENCES tasks(id) ON DELETE CASCADE
                        )
                    """)
                    # Create index on task_logs(task_id)
                    conn.execute("CREATE INDEX IF NOT EXISTS idx_task_logs_task_id ON task_logs(task_id)")
            finally:
                conn.close()

    def create_task(self, task_id: str):
        with self._lock:
            conn = self._get_connection()
            try:
                with conn:
                    conn.execute(
                        "INSERT INTO tasks (id, percentage, status, completed, created_at) VALUES (?, 0, 'Pending', 0, ?)",
                        (task_id, time.time())
                    )
            finally:
                conn.close()

    def update_task(
        self,
        task_id: str,
        percentage: Optional[int] = None,
        status: Optional[str] = None,
        completed: Optional[bool] = None,
        audio_file: Optional[str] = None,
        error: Optional[str] = None
    ):
        updates = []
        params = []
        if percentage is not None:
            updates.append("percentage = ?")
            params.append(percentage)
        if status is not None:
            updates.append("status = ?")
            params.append(status)
        if completed is not None:
            updates.append("completed = ?")
            params.append(1 if completed else 0)
        if audio_file is not None:
            updates.append("audio_file = ?")
            params.append(audio_file)
        if error is not None:
            updates.append("error = ?")
            params.append(error)
            
        if not updates:
            return
            
        params.append(task_id)
        query = f"UPDATE tasks SET {', '.join(updates)} WHERE id = ?"
        
        with self._lock:
            conn = self._get_connection()
            try:
                with conn:
                    conn.execute(query, tuple(params))
            finally:
                conn.close()

    def add_log(self, task_id: str, message: str):
        with self._lock:
            conn = self._get_connection()
            try:
                with conn:
                    conn.execute(
                        "INSERT INTO task_logs (task_id, message, created_at) VALUES (?, ?, ?)",
                        (task_id, message, time.time())
                    )
            finally:
                conn.close()

    def get_task(self, task_id: str) -> Optional[Dict[str, Any]]:
        conn = self._get_connection()
        try:
            row = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
            if row:
                d = dict(row)
                d["completed"] = bool(d["completed"])
                return d
            return None
        finally:
            conn.close()

    def get_logs(self, task_id: str, after_id: int = 0) -> List[Dict[str, Any]]:
        conn = self._get_connection()
        try:
            cursor = conn.execute(
                "SELECT id, message, created_at FROM task_logs WHERE task_id = ? AND id > ? ORDER BY id ASC",
                (task_id, after_id)
            )
            return [dict(row) for row in cursor.fetchall()]
        finally:
            conn.close()

    def delete_old_tasks(self, cutoff_time: float) -> int:
        with self._lock:
            conn = self._get_connection()
            try:
                with conn:
                    cursor = conn.execute("DELETE FROM tasks WHERE created_at < ?", (cutoff_time,))
                    return cursor.rowcount
            finally:
                conn.close()
