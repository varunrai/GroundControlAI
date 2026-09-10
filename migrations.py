import sqlite3
import os

def run_migrations(db_path="/app/db/activity.db"):
    if not os.path.exists(db_path):
        os.makedirs(os.path.dirname(os.path.abspath(db_path)), exist_ok=True)
        
    conn = sqlite3.connect(db_path, timeout=30.0)
    cursor = conn.cursor()
    cursor.execute("PRAGMA journal_mode=WAL;")
    cursor.execute("PRAGMA busy_timeout=30000;")

    # Ensure baseline tables exist
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS sessions (
        id TEXT PRIMARY KEY,
        agent_type TEXT,
        project_path TEXT,
        start_time DATETIME
    )
    ''')
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS activities (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        session_id TEXT,
        timestamp DATETIME,
        content TEXT,
        action_type TEXT,
        UNIQUE(session_id, timestamp, content)
    )
    ''')

    # Extend sessions columns
    cursor.execute("PRAGMA table_info(sessions)")
    existing_session_cols = [r[1] for r in cursor.fetchall()]
    session_cols_to_add = [
        ("git_branch", "TEXT DEFAULT 'main'"),
        ("model", "TEXT DEFAULT 'unknown'"),
        ("cli_version", "TEXT"),
        ("total_input_tokens", "INTEGER DEFAULT 0"),
        ("total_output_tokens", "INTEGER DEFAULT 0"),
        ("total_cache_read_tokens", "INTEGER DEFAULT 0"),
        ("total_cache_creation_tokens", "INTEGER DEFAULT 0"),
        ("total_thinking_tokens", "INTEGER DEFAULT 0"),
        ("estimated_cost_usd", "REAL DEFAULT 0.0")
    ]
    for col_name, col_def in session_cols_to_add:
        if col_name not in existing_session_cols:
            cursor.execute(f"ALTER TABLE sessions ADD COLUMN {col_name} {col_def}")

    # Extend activities columns
    cursor.execute("PRAGMA table_info(activities)")
    existing_act_cols = [r[1] for r in cursor.fetchall()]
    act_cols_to_add = [
        ("model", "TEXT"),
        ("prompt_tokens", "INTEGER DEFAULT 0"),
        ("completion_tokens", "INTEGER DEFAULT 0"),
        ("cache_read_tokens", "INTEGER DEFAULT 0"),
        ("cache_creation_tokens", "INTEGER DEFAULT 0"),
        ("thinking_tokens", "INTEGER DEFAULT 0"),
        ("cost_usd", "REAL DEFAULT 0.0"),
        ("first_token_latency_ms", "INTEGER DEFAULT 0"),
        ("stream_duration_ms", "INTEGER DEFAULT 0"),
        ("tokens_per_sec", "REAL DEFAULT 0.0")
    ]
    for col_name, col_def in act_cols_to_add:
        if col_name not in existing_act_cols:
            cursor.execute(f"ALTER TABLE activities ADD COLUMN {col_name} {col_def}")

    # Create tool_executions table
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS tool_executions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        session_id TEXT NOT NULL,
        activity_id INTEGER,
        tool_name TEXT NOT NULL,
        command TEXT,
        exit_code INTEGER DEFAULT 0,
        duration_ms INTEGER DEFAULT 0,
        stdout_snippet TEXT,
        stderr_snippet TEXT,
        status TEXT DEFAULT 'success',
        timestamp DATETIME NOT NULL,
        FOREIGN KEY(session_id) REFERENCES sessions(id) ON DELETE CASCADE
    )
    ''')

    # Create file_hotspots table
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS file_hotspots (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        session_id TEXT NOT NULL,
        project_path TEXT NOT NULL,
        file_path TEXT NOT NULL,
        operation TEXT NOT NULL,
        timestamp DATETIME NOT NULL,
        FOREIGN KEY(session_id) REFERENCES sessions(id) ON DELETE CASCADE
    )
    ''')

    # Create model_pricing table & seed
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS model_pricing (
        model_pattern TEXT PRIMARY KEY,
        input_usd_per_m REAL,
        cache_read_usd_per_m REAL,
        cache_create_usd_per_m REAL,
        output_usd_per_m REAL
    )
    ''')
    cursor.executemany('''
    INSERT OR REPLACE INTO model_pricing VALUES (?, ?, ?, ?, ?)
    ''', [
        ('claude-sonnet-5', 3.00, 0.30, 3.75, 15.00),
        ('claude-opus-4',  15.00, 1.50, 18.75, 75.00),
        ('claude-haiku',    0.80, 0.08,  1.00,  4.00),
        ('k3-256k',         0.70, 0.10,  0.70,  2.00),
        ('gemini-2.5-pro',  1.25, 0.30,  1.25,  5.00)
    ])

    # Optimize indexes
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_sessions_project ON sessions(project_path, start_time DESC);")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_activities_session ON activities(session_id, timestamp DESC);")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_tool_exec_session ON tool_executions(session_id, timestamp DESC);")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_file_hotspots_path ON file_hotspots(project_path, file_path);")

    # Normalize existing session & hotspot project paths
    try:
        from normalizer import normalize_project_path
        cursor.execute("SELECT id, project_path FROM sessions")
        for sid, p in cursor.fetchall():
            norm = normalize_project_path(p)
            if norm != p:
                cursor.execute("UPDATE sessions SET project_path = ? WHERE id = ?", (norm, sid))

        cursor.execute("SELECT id, project_path FROM file_hotspots")
        for hid, p in cursor.fetchall():
            norm = normalize_project_path(p)
            if norm != p:
                cursor.execute("UPDATE file_hotspots SET project_path = ? WHERE id = ?", (norm, hid))
    except Exception as e:
        print(f"⚠️ Project path normalization note: {e}")

    conn.commit()
    conn.close()
    print("✅ Database migrations completed successfully.")

if __name__ == "__main__":
    db = "/app/db/activity.db" if os.path.exists("/app/db") else "db/activity.db"
    run_migrations(db)
