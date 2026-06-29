# Robust Task State Management Implementation Plan

> **For Gemini:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Transition the WebUI's task tracking and logging from in-memory dictionary stores to a persistent SQLite database, introducing robust error handling, automated background purging, and an optimized SSE log stream.

**Architecture:** We use a thread-safe `TaskDatabase` helper class in `src/core/task_db.py` backed by SQLite. Active logging is routed to this database via the FastAPI `TaskLogHandler`. A background task handles the deletion of records older than 24 hours.

**Tech Stack:** Python 3.11, FastAPI, HTML5 Server-Sent Events, standard library `sqlite3` and `asyncio`.

---

### Task 1: Create Database Helper and Unit Tests

**Files:**
- Create: `src/core/task_db.py`
- Create: `tests/test_task_db.py`

**Step 1: Write the failing test**
Create `tests/test_task_db.py`:
```python
import pytest
import time
from pathlib import Path
from src.core.task_db import TaskDatabase

def test_database_lifecycle(tmp_path):
    db_path = tmp_path / "test.db"
    db = TaskDatabase(db_path)
    
    # 1. Create task
    task_id = "test-task-123"
    db.create_task(task_id)
    
    # 2. Get task
    task = db.get_task(task_id)
    assert task["id"] == task_id
    assert task["percentage"] == 0
    assert task["status"] == "Pending"
    assert task["completed"] == 0
    
    # 3. Add logs
    db.add_log(task_id, "Log line 1")
    db.add_log(task_id, "Log line 2")
    
    logs = db.get_logs(task_id)
    assert len(logs) == 2
    assert logs[0]["message"] == "Log line 1"
    
    # Test offset log retrieval
    first_log_id = logs[0]["id"]
    new_logs = db.get_logs(task_id, after_id=first_log_id)
    assert len(new_logs) == 1
    assert new_logs[0]["message"] == "Log line 2"
    
    # 4. Update task
    db.update_task(task_id, percentage=50, status="Generating Audio")
    task = db.get_task(task_id)
    assert task["percentage"] == 50
    assert task["status"] == "Generating Audio"
    
    # 5. Delete old tasks
    purged = db.delete_old_tasks(time.time() + 10)
    assert purged == 1
    assert db.get_task(task_id) is None
    # Cascaded delete check
    assert len(db.get_logs(task_id)) == 0
```

**Step 2: Run test to verify it fails**
Run: `PYTHONPATH=. pytest tests/test_task_db.py`
Expected: FAIL (ModuleNotFoundError: No module named 'src.core.task_db')

**Step 3: Implement TaskDatabase in `src/core/task_db.py`**
Create `src/core/task_db.py`:
```python
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
```

**Step 4: Run test to verify it passes**
Run: `PYTHONPATH=. pytest tests/test_task_db.py`
Expected: PASS

**Step 5: Commit**
```bash
git add src/core/task_db.py tests/test_task_db.py
git commit -m "feat: implement TaskDatabase and associated lifecycle tests"
```

---

### Task 2: Initialize Database and Integrate TaskLogHandler in `src/web.py`

**Files:**
- Modify: `src/web.py`
- Test: `tests/test_web.py`

**Step 1: Update `TaskLogHandler` in `src/web.py`**
Modify `src/web.py` (lines 75-104) to instantiate `TaskDatabase` and rewrite `TaskLogHandler`:
- Remove `progress_store = {}` (we will declare `db = TaskDatabase(Path("storage/state.db"))`).
- Update `TaskLogHandler` to use `db.add_log(task_id, log_entry)` instead of appending to `self.store`.
- Since tests mock logging or fetch progress, we must make sure database queries work smoothly.

Let's adapt `src/web.py`:
```python
from src.core.task_db import TaskDatabase

# Initialize Task Database
db = TaskDatabase(Path("storage/state.db"))

class TaskLogHandler(logging.Handler):
    def __init__(self, database: TaskDatabase):
        super().__init__()
        self.database = database
        self.setFormatter(logging.Formatter("%(asctime)s - %(levelname)s - %(message)s", datefmt="%H:%M:%S"))

    def emit(self, record):
        try:
            task_id = current_task_id.get()
            if task_id:
                log_entry = self.format(record)
                self.database.add_log(task_id, log_entry)
        except Exception:
            self.handleError(record)

# Register global logging handler
global_log_handler = TaskLogHandler(db)
logging.getLogger("booksmith").addHandler(global_log_handler)
logging.getLogger("src").addHandler(global_log_handler)
```

**Step 2: Commit**
```bash
git add src/web.py
git commit -m "refactor: integrate TaskDatabase with TaskLogHandler in web backend"
```

---

### Task 3: Refactor generate, progress, and status API endpoints

**Files:**
- Modify: `src/web.py`
- Test: `tests/test_web.py`

**Step 1: Check existing web tests**
Run: `PYTHONPATH=. pytest tests/test_web.py`
Expected: FAIL (because tests mock or access `progress_store` directly)

**Step 2: Refactor API endpoints in `src/web.py`**
Modify the endpoints in `src/web.py`:
- In `generate_audiobook()`:
  - Create a database entry: `db.create_task(task_id)`.
  - Remove direct mutations to `progress_store[task_id]`.
- In `get_progress()`:
  - Accept `last_log_id: int = Query(0)` parameter to support SSE log offset optimization.
  - Query database:
    ```python
    task_state = db.get_task(task_id)
    if not task_state:
        raise HTTPException(status_code=404, detail="Task not found")
    ```
  - Fetch new logs: `logs = db.get_logs(task_id, after_id=last_log_id)`.
  - Format the SSE payload cleanly to yield `task_state` (which now has metadata like percentage and status) and the list of *new* logs.
  - Make sure the stream exits if `task_state["completed"]` or status is `"Failed"`.

Let's modify the SSE payload format:
```python
@app.get("/api/progress")
async def get_progress(task_id: str = Query(...), last_log_id: int = Query(0), session: str = Depends(verify_session)):
    if not db.get_task(task_id):
        raise HTTPException(status_code=404, detail="Task not found")

    async def event_generator():
        current_last_id = last_log_id
        while True:
            task_state = db.get_task(task_id)
            if not task_state:
                break
                
            new_logs = db.get_logs(task_id, after_id=current_last_id)
            if new_logs:
                current_last_id = new_logs[-1]["id"]
                
            # Yield metadata along with the chunk of logs
            payload = {
                "percentage": task_state["percentage"],
                "status": task_state["status"],
                "completed": task_state["completed"],
                "audio_file": task_state["audio_file"],
                "error": task_state["error"],
                "logs": [l["message"] for l in new_logs],
                "last_log_id": current_last_id
            }
            
            yield f"data: {json.dumps(payload)}\n\n"
            if task_state["completed"] or task_state["status"] == "Failed":
                break
            await asyncio.sleep(0.5)

    return StreamingResponse(event_generator(), media_type="text/event-stream")
```

**Step 3: Fix `tests/test_web.py`**
Refactor the tests in `tests/test_web.py` that query task states or logs. Use standard database queries (by importing `db` from `src.web` and calling `db.get_task` or checking mock pipeline inputs).
Specifically, in `tests/test_web.py`:
- Replace any references to `progress_store` with queries to `db.get_task` or `db.get_logs`.

**Step 4: Run tests to verify they pass**
Run: `PYTHONPATH=. pytest tests/test_web.py`
Expected: PASS

**Step 5: Commit**
```bash
git add src/web.py tests/test_web.py
git commit -m "feat: refactor API endpoints and web tests to use SQLite task states"
```

---

### Task 4: Update Background Pipeline to Write Progress to SQLite

**Files:**
- Modify: `src/web.py:run_generation_pipeline`
- Test: `tests/test_web.py`

**Step 1: Refactor `run_generation_pipeline()`**
Inside `run_generation_pipeline()`:
- Change all `progress_store[task_id]["percentage"] = ...` calls to `db.update_task(task_id, percentage=...)`.
- Change all `progress_store[task_id]["status"] = ...` calls to `db.update_task(task_id, status=...)`.
- When pipeline finishes:
  ```python
  db.update_task(
      task_id,
      percentage=100,
      status="Completed",
      completed=True,
      audio_file=output_filename
  )
  ```
- When pipeline errors:
  ```python
  db.update_task(
      task_id,
      status="Failed",
      error=str(e)
  )
  ```

**Step 2: Run all tests to verify pipeline logic still runs and passes**
Run: `PYTHONPATH=. pytest`
Expected: PASS

**Step 3: Commit**
```bash
git add src/web.py
git commit -m "feat: update background run_generation_pipeline to persist status to SQLite"
```

---

### Task 5: Implement Background Purger Task Loop

**Files:**
- Modify: `src/web.py`
- Test: `tests/test_web.py` (add a purger loop integration test)

**Step 1: Write integration test for the purger loop**
Add a test in `tests/test_web.py` validating that the purger background loop successfully purges older tasks:
```python
@pytest.mark.anyio
async def test_background_purger(tmp_path):
    from src.web import db
    import time
    
    # Create old task
    old_id = "old-task-999"
    db.create_task(old_id)
    # Manually modify created_at in DB to make it old
    conn = db._get_connection()
    conn.execute("UPDATE tasks SET created_at = ? WHERE id = ?", (time.time() - 90000, old_id))
    conn.commit()
    conn.close()
    
    # Run a single deletion check
    db.delete_old_tasks(time.time() - 86400)
    
    assert db.get_task(old_id) is None
```

**Step 2: Implement periodic task in `src/web.py`**
Add an async purger loop function and wire it to FastAPI lifecycle startup:
```python
async def task_purger_loop():
    """Background task loop that purges tasks older than 24 hours every 30 minutes."""
    while True:
        try:
            cutoff = time.time() - 86400
            purged = db.delete_old_tasks(cutoff)
            if purged > 0:
                logger.info(f"Background purger evicted {purged} tasks older than 24 hours.")
        except Exception as e:
            logger.error(f"Error running background task purger: {e}", exc_info=True)
        await asyncio.sleep(1800)  # 30 minutes

@app.on_event("startup")
async def startup_event():
    # Start the purger loop in the background
    asyncio.create_task(task_purger_loop())
```

**Step 3: Run all tests**
Run: `PYTHONPATH=. pytest`
Expected: PASS

**Step 4: Commit**
```bash
git add src/web.py tests/test_web.py
git commit -m "feat: add periodic background purger loop to evict tasks older than 24 hours"
```

---

### Task 6: Optimize Frontend SSE Stream Client

**Files:**
- Modify: `src/web/static/app.js`

**Step 1: Refactor `startProgressStream` in `app.js`**
Modify `app.js` (lines 300-368):
- Maintain a local state variable `let lastLogId = 0;` inside `startProgressStream`.
- When constructing `EventSource`, pass `last_log_id` query parameter:
  ```javascript
  eventSource = new EventSource(`/api/progress?task_id=${taskId}&last_log_id=${lastLogId}`);
  ```
  Wait! Standard `EventSource` doesn't easily let us change URL query params dynamically once connected. But wait! The SSE connection is a continuous streaming connection from the server. The server keeps the connection open and loops on its side.
  Ah! Since the server loops on its side, the server itself can track `current_last_id` on its connection context loop!
  Let's look at the server code we designed in Task 3:
  ```python
  async def event_generator():
      current_last_id = last_log_id
      while True:
          # Server loops and updates current_last_id itself!
          new_logs = db.get_logs(task_id, after_id=current_last_id)
          if new_logs:
              current_last_id = new_logs[-1]["id"]
  ```
  Yes! The server handles log offset paging internally in the active connection loop. The client doesn't need to reconnect to update `last_log_id`!
  However, what if the client disconnects and reconnects? If so, the client can pass `last_log_id` in the initial connection parameters to avoid receiving duplicate history.
  Let's modify `app.js` to:
  - Extract `last_log_id` from the SSE message payload:
    ```javascript
    const state = JSON.parse(event.data);
    if (state.last_log_id !== undefined) {
        lastLogId = state.last_log_id;
    }
    ```
  - When re-connecting or establishing the initial `EventSource` connection, pass the latest `lastLogId`:
    ```javascript
    eventSource = new EventSource(`/api/progress?task_id=${taskId}&last_log_id=${lastLogId}`);
    ```
  - Ensure the client does not clear the console output if `lastLogId > 0` (this ensures logs are concatenated correctly even if connection drops and reconnects).

**Step 2: Verify WebUI functionality manually**
- Start the server: `python3 -m uvicorn src.web:app --host 0.0.0.0 --port 8000`
- Open WebUI, run synthesis, and ensure progress logs render correctly.

**Step 3: Commit**
```bash
git add src/web/static/app.js
git commit -m "feat: optimize frontend SSE client to support log offset paging on reconnection"
```
