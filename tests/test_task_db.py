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
