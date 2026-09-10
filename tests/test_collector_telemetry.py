import json
import sqlite3
import os
import pytest

def test_claude_telemetry_extraction(tmp_path):
    test_db = str(tmp_path / "activity.db")
    from migrations import run_migrations
    run_migrations(test_db)
    
    # Mock claude transcript
    transcript = tmp_path / "session_test.jsonl"
    line_data = {
        "type": "assistant",
        "sessionId": "test-session-123",
        "cwd": "/mock/projects/test-repo",
        "gitBranch": "feat/telemetry",
        "message": {
            "model": "claude-sonnet-5",
            "content": [
                {"type": "tool_use", "name": "Bash", "input": {"command": "pytest -q"}},
                {"type": "text", "text": "Running tests"}
            ],
            "usage": {
                "input_tokens": 100,
                "output_tokens": 50,
                "cache_read_input_tokens": 500,
                "cache_creation_input_tokens": 0,
                "output_tokens_details": {"thinking_tokens": 20}
            }
        },
        "timestamp": "2026-09-10T12:00:00Z"
    }
    with open(transcript, "w") as f:
        f.write(json.dumps(line_data) + "\n")
        
    import collector
    old_db = collector.DB_PATH
    collector.DB_PATH = test_db
    try:
        collector.process_claude_file(str(transcript))
        conn = sqlite3.connect(test_db)
        cursor = conn.cursor()
        cursor.execute("SELECT model, prompt_tokens, cache_read_tokens, thinking_tokens, cost_usd FROM activities WHERE session_id='test-session-123'")
        row = cursor.fetchone()
        assert row is not None
        assert row[0] == "claude-sonnet-5"
        assert row[1] == 100
        assert row[2] == 500
        assert row[3] == 20
        assert row[4] > 0.0
        
        # Verify tool execution created
        cursor.execute("SELECT tool_name, command FROM tool_executions WHERE session_id='test-session-123'")
        trow = cursor.fetchone()
        assert trow is not None
        assert trow[0] == "Bash"
        assert "pytest -q" in trow[1]
        conn.close()
    finally:
        collector.DB_PATH = old_db

def test_kimi_telemetry_extraction(tmp_path):
    test_db = str(tmp_path / "activity.db")
    from migrations import run_migrations
    run_migrations(test_db)

    # Mimic Kimi dir structure: sessions/<hash>/<session_id>/agents/main/wire.jsonl
    session_dir = tmp_path / "sessions" / "wd_123" / "session_kimi_999"
    main_dir = session_dir / "agents" / "main"
    main_dir.mkdir(parents=True, exist_ok=True)
    wire_file = main_dir / "wire.jsonl"
    
    # State file
    state_file = session_dir / "state.json"
    with open(state_file, "w") as sf:
        json.dump({"id": "session_kimi_999", "workDir": "/mock/projects/kimi-project"}, sf)

    events = [
        {"type": "turn.prompt", "input": [{"type": "text", "text": "Check system status"}], "time": 1785417140000},
        {"type": "context.append_loop_event", "event": {"type": "content.part", "part": {"type": "text", "text": "Analyzing system..."}}, "time": 1785417145000},
        {"type": "context.append_loop_event", "event": {"type": "tool.call", "name": "Bash", "args": {"command": "uptime"}, "display": {"kind": "system"}}, "time": 1785417146000},
        {"type": "context.append_loop_event", "event": {"type": "step.end", "usage": {"inputOther": 400, "output": 80, "inputCacheRead": 2000, "inputCacheCreation": 0}, "llmFirstTokenLatencyMs": 1450, "llmStreamDurationMs": 1200}, "time": 1785417148000}
    ]
    with open(wire_file, "w") as wf:
        for ev in events:
            wf.write(json.dumps(ev) + "\n")

    import collector
    old_db = collector.DB_PATH
    collector.DB_PATH = test_db
    try:
        collector.process_kimi_session(str(wire_file))
        conn = sqlite3.connect(test_db)
        cursor = conn.cursor()
        
        cursor.execute("SELECT model, prompt_tokens, first_token_latency_ms FROM activities WHERE session_id='session_kimi_999' AND first_token_latency_ms > 0")
        row = cursor.fetchone()
        assert row is not None
        assert row[0] == "k3-256k"
        assert row[1] == 400
        assert row[2] == 1450

        cursor.execute("SELECT tool_name, command FROM tool_executions WHERE session_id='session_kimi_999'")
        trow = cursor.fetchone()
        assert trow is not None
        assert trow[0] == "Bash"
        assert trow[1] == "uptime"
        conn.close()
    finally:
        collector.DB_PATH = old_db
