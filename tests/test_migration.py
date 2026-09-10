import sqlite3
import os
import pytest
from migrations import run_migrations

def test_migration_creates_telemetry_schema(tmp_path):
    test_db = str(tmp_path / "test_activity.db")
    conn = sqlite3.connect(test_db)
    conn.execute("CREATE TABLE sessions (id TEXT PRIMARY KEY, agent_type TEXT, project_path TEXT, start_time DATETIME)")
    conn.execute("CREATE TABLE activities (id INTEGER PRIMARY KEY, session_id TEXT, timestamp DATETIME, content TEXT, action_type TEXT)")
    conn.commit()
    conn.close()

    run_migrations(test_db)

    conn = sqlite3.connect(test_db)
    cursor = conn.cursor()
    
    # Verify new columns on activities
    cursor.execute("PRAGMA table_info(activities)")
    cols = [r[1] for r in cursor.fetchall()]
    assert "prompt_tokens" in cols
    assert "cache_read_tokens" in cols
    assert "cost_usd" in cols
    assert "first_token_latency_ms" in cols

    # Verify tool_executions table exists
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='tool_executions'")
    assert cursor.fetchone() is not None

    # Verify model_pricing seeded
    cursor.execute("SELECT COUNT(*) FROM model_pricing")
    count = cursor.fetchone()[0]
    assert count >= 5

    conn.close()
