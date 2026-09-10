from fastapi.testclient import TestClient
import sqlite3
import os
import pytest

from app import app
import app as app_module

def test_api_cockpit_aggregates(tmp_path):
    test_db = str(tmp_path / "activity.db")
    from migrations import run_migrations
    run_migrations(test_db)
    
    # Insert mock session, activity, tool execution, hotspot
    conn = sqlite3.connect(test_db)
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO sessions (id, agent_type, project_path, start_time, model, total_input_tokens, total_output_tokens, estimated_cost_usd)
        VALUES ('sess-1', 'Claude Code', '/mock/projects/mock-repo', '2026-09-10T12:00:00Z', 'claude-sonnet-5', 1000, 200, 0.05)
    ''')
    cursor.execute('''
        INSERT INTO activities (session_id, timestamp, content, action_type, model, prompt_tokens, completion_tokens, cache_read_tokens, cost_usd, first_token_latency_ms)
        VALUES ('sess-1', '2026-09-10T12:00:00Z', 'Ran tests', 'PLANNER_RESPONSE', 'claude-sonnet-5', 1000, 200, 500, 0.05, 1200)
    ''')
    cursor.execute('''
        INSERT INTO tool_executions (session_id, tool_name, command, exit_code, timestamp)
        VALUES ('sess-1', 'Bash', 'pytest', 0, '2026-09-10T12:00:00Z')
    ''')
    cursor.execute('''
        INSERT INTO file_hotspots (session_id, project_path, file_path, operation, timestamp)
        VALUES ('sess-1', '/mock/projects/mock-repo', 'tests/test_foo.py', 'read', '2026-09-10T12:00:00Z')
    ''')
    conn.commit()
    conn.close()

    old_db = app_module.DB_PATH
    app_module.DB_PATH = test_db
    try:
        client = TestClient(app)
        response = client.get("/")
        assert response.status_code == 200
        assert "mock-repo" in response.text
    finally:
        app_module.DB_PATH = old_db
