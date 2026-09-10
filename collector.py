import os
import json
import sqlite3
import time
import threading
from datetime import datetime
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

from pricing import calculate_cost_and_savings
from migrations import run_migrations
from normalizer import normalize_project_path, get_project_display_name

DB_PATH = "/app/db/activity.db"

# Track file byte offsets so we only read new lines on change
file_offsets = {}
offsets_lock = threading.Lock()

def init_db():
    """Initialize or migrate the SQLite database schema."""
    run_migrations(DB_PATH)

def get_db_connection():
    conn = sqlite3.connect(DB_PATH, timeout=30.0)
    conn.execute("PRAGMA busy_timeout=30000;")
    return conn

def to_iso_timestamp(ts):
    if not ts:
        return datetime.now().isoformat()
    if isinstance(ts, (int, float)):
        if ts > 1e11:  # milliseconds
            ts = ts / 1000.0
        return datetime.fromtimestamp(ts).isoformat()
    elif isinstance(ts, str):
        if ts.isdigit():
            v = float(ts)
            if v > 1e11:
                v = v / 1000.0
            return datetime.fromtimestamp(v).isoformat()
        return ts
    return str(ts)

# ==============================================================================
# AGY SINGLE FILE PROCESSOR
# ==============================================================================
def process_agy_file(transcript_path, session_id):
    if not os.path.exists(transcript_path):
        return 0

    with offsets_lock:
        offset = file_offsets.get(transcript_path, 0)

    try:
        file_size = os.path.getsize(transcript_path)
        if offset > file_size:
            offset = 0  # File was truncated or rotated
    except OSError:
        return 0

    activities_to_insert = []
    tools_to_insert = []
    hotspots_to_insert = []
    project_path = "Agy Session"
    start_time = datetime.now().isoformat()

    try:
        with open(transcript_path, 'r', encoding='utf-8') as f:
            if offset > 0:
                f.seek(offset)
            
            for line in f:
                if not line.strip():
                    continue
                try:
                    data = json.loads(line)
                    if data.get("type") in ["USER_INPUT", "PLANNER_RESPONSE"]:
                        content = data.get("content", "")
                        timestamp = data.get("created_at") or datetime.now().isoformat()
                        action_type = data.get("type")
                        
                        tool_calls = data.get("tool_calls", [])
                        thinking = data.get("thinking", "")
                        thinking_tokens = len(thinking) // 4 if thinking else 0
                        model = "gemini-2.5-pro" if action_type == "PLANNER_RESPONSE" else None

                        if tool_calls:
                            tool_summaries = []
                            for tc in tool_calls:
                                name = tc.get("name", "tool")
                                args = tc.get("arguments", {})
                                if not isinstance(args, dict):
                                    args = {}
                                
                                for key in ["Cwd", "TargetFile", "AbsolutePath", "DirectoryPath", "SearchDirectory", "SearchPath"]:
                                    if key in args and "/Sources" in str(args[key]):
                                        parts = str(args[key]).split('/')
                                        try:
                                            idx = parts.index("Sources")
                                            project_path = "/".join(parts[:idx+2])
                                        except ValueError:
                                            project_path = str(args[key])

                                # File Hotspots
                                for file_key in ["TargetFile", "AbsolutePath"]:
                                    if file_key in args:
                                        hotspots_to_insert.append((
                                            session_id,
                                            normalize_project_path(project_path),
                                            str(args[file_key]),
                                            "write" if "write" in name.lower() or "edit" in name.lower() else "read",
                                            timestamp
                                        ))

                                cmd = args.get("CommandLine") if name == "run_command" else None
                                tools_to_insert.append((
                                    session_id, None, name, cmd, 0, 0, None, None, 'success', timestamp
                                ))
                                tool_summaries.append(f"Used tool: {name}")
                            
                            if not content and tool_summaries:
                                content = " | ".join(tool_summaries)
                            
                        if not content:
                            continue
                            
                        project_path = normalize_project_path(project_path)
                        activities_to_insert.append((
                            session_id, timestamp, content, action_type,
                            model, 0, 0, 0, 0, thinking_tokens, 0.0, 0, 0, 0.0
                        ))
                except json.JSONDecodeError:
                    continue
            
            new_offset = f.tell()
    except Exception as e:
        print(f"Error reading Agy transcript {transcript_path}: {e}")
        return 0

    with offsets_lock:
        file_offsets[transcript_path] = new_offset

    if activities_to_insert:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute('''
        INSERT OR IGNORE INTO sessions (id, agent_type, project_path, start_time, model)
        VALUES (?, ?, ?, ?, ?)
        ''', (session_id, 'Agy', project_path, start_time, 'gemini-2.5-pro'))
        
        for act in activities_to_insert:
            cursor.execute('''
            INSERT OR IGNORE INTO activities (
                session_id, timestamp, content, action_type,
                model, prompt_tokens, completion_tokens, cache_read_tokens,
                cache_creation_tokens, thinking_tokens, cost_usd,
                first_token_latency_ms, stream_duration_ms, tokens_per_sec
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', act)

        for t in tools_to_insert:
            cursor.execute('''
            INSERT INTO tool_executions (session_id, activity_id, tool_name, command, exit_code, duration_ms, stdout_snippet, stderr_snippet, status, timestamp)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', t)

        for h in hotspots_to_insert:
            cursor.execute('''
            INSERT INTO file_hotspots (session_id, project_path, file_path, operation, timestamp)
            VALUES (?, ?, ?, ?, ?)
            ''', h)

        conn.commit()
        conn.close()
        print(f"📥 [Agy] Ingested {len(activities_to_insert)} events from {session_id[:8]}")

    return len(activities_to_insert)

# ==============================================================================
# CLAUDE CODE SINGLE FILE PROCESSOR
# ==============================================================================
def clean_claude_content(raw_content):
    import re
    if isinstance(raw_content, str):
        text = raw_content.strip()
        if text.startswith("<local-command-caveat>"):
            return None
        if "<command-name>" in text:
            m = re.search(r"<command-name>(.*?)</command-name>", text)
            if m:
                return m.group(1).strip()
        if "<local-command-stdout>" in text:
            m = re.search(r"<local-command-stdout>(.*?)</local-command-stdout>", text, re.DOTALL)
            if m:
                return m.group(1).strip()
        return text
    elif isinstance(raw_content, list):
        parts = []
        for block in raw_content:
            if isinstance(block, dict):
                btype = block.get("type")
                if btype == "text":
                    t = block.get("text", "").strip()
                    if t:
                        parts.append(t)
                elif btype == "tool_use":
                    tname = block.get("name", "tool")
                    inp = block.get("input", {})
                    if tname == "Bash" and "command" in inp:
                        cmd = inp["command"].strip().replace("\n", " ")
                        if len(cmd) > 80:
                            cmd = cmd[:77] + "..."
                        parts.append("Ran: " + cmd)
                    elif tname in ["Read", "Edit", "Write", "View"] and "file_path" in inp:
                        parts.append(tname + ": " + str(inp.get("file_path")))
                    else:
                        parts.append("Tool: " + str(tname))
        return " | ".join(parts).strip() if parts else None
    return None

def process_claude_file(file_path):
    if not os.path.exists(file_path):
        return 0

    with offsets_lock:
        offset = file_offsets.get(file_path, 0)

    try:
        file_size = os.path.getsize(file_path)
        if offset > file_size:
            offset = 0
    except OSError:
        return 0

    activities_to_insert = []
    tools_to_insert = []
    hotspots_to_insert = []
    session_id = os.path.basename(file_path).replace(".jsonl", "")
    project_path = "Unknown Claude Workspace"
    start_time = datetime.now().isoformat()
    git_branch = "main"
    cli_version = None
    active_model = "claude-sonnet-5"

    session_input_tokens = 0
    session_output_tokens = 0
    session_cache_read = 0
    session_cache_create = 0
    session_thinking = 0
    session_cost = 0.0

    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            if offset > 0:
                f.seek(offset)
                
            for line in f:
                if not line.strip():
                    continue
                try:
                    data = json.loads(line)
                    session_id = data.get("sessionId", session_id)
                    project_path = normalize_project_path(data.get("cwd", project_path))
                    git_branch = data.get("gitBranch", git_branch)
                    cli_version = data.get("version", cli_version)
                    
                    msg = data.get("message", {})
                    role = msg.get("role") or data.get("type")
                    if role not in ["user", "assistant"]:
                        continue
                    
                    content = clean_claude_content(msg.get("content"))
                    if not content:
                        continue
                        
                    timestamp = data.get("timestamp", datetime.now().isoformat())
                    action_type = "USER_INPUT" if role == "user" else "PLANNER_RESPONSE"
                    
                    # Telemetry fields
                    model = msg.get("model") if role == "assistant" else None
                    if model:
                        active_model = model
                    usage = msg.get("usage", {})
                    prompt_tokens = usage.get("input_tokens", 0)
                    output_tokens = usage.get("output_tokens", 0)
                    cache_read = usage.get("cache_read_input_tokens", 0)
                    cache_create = usage.get("cache_creation_input_tokens", 0)
                    
                    thinking_tokens = 0
                    if isinstance(usage.get("output_tokens_details"), dict):
                        thinking_tokens = usage.get("output_tokens_details", {}).get("thinking_tokens", 0)
                        
                    cost_usd, _, _ = calculate_cost_and_savings(model or active_model, prompt_tokens, cache_read, cache_create, output_tokens)

                    session_input_tokens += prompt_tokens
                    session_output_tokens += output_tokens
                    session_cache_read += cache_read
                    session_cache_create += cache_create
                    session_thinking += thinking_tokens
                    session_cost += cost_usd

                    # Parse tool executions and hotspots
                    raw_content = msg.get("content")
                    if isinstance(raw_content, list):
                        for block in raw_content:
                            if isinstance(block, dict) and block.get("type") == "tool_use":
                                tname = block.get("name", "tool")
                                inp = block.get("input", {})
                                cmd = inp.get("command") if tname == "Bash" else None
                                tools_to_insert.append((
                                    session_id, None, tname, cmd, 0, 0, None, None, 'success', timestamp
                                ))
                                if tname in ["Read", "Edit", "Write", "View"] and "file_path" in inp:
                                    hotspots_to_insert.append((
                                        session_id, project_path, str(inp.get("file_path")), tname.lower(), timestamp
                                    ))

                    activities_to_insert.append((
                        session_id, timestamp, content, action_type,
                        model, prompt_tokens, output_tokens, cache_read,
                        cache_create, thinking_tokens, cost_usd,
                        0, 0, 0.0
                    ))
                except json.JSONDecodeError:
                    continue
            new_offset = f.tell()
    except Exception as e:
        print(f"Error reading Claude file {file_path}: {e}")
        return 0

    with offsets_lock:
        file_offsets[file_path] = new_offset

    if activities_to_insert:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute('''
        INSERT INTO sessions (
            id, agent_type, project_path, start_time, git_branch, model, cli_version,
            total_input_tokens, total_output_tokens, total_cache_read_tokens,
            total_cache_creation_tokens, total_thinking_tokens, estimated_cost_usd
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET
            project_path=excluded.project_path,
            git_branch=COALESCE(excluded.git_branch, sessions.git_branch),
            model=COALESCE(excluded.model, sessions.model),
            cli_version=COALESCE(excluded.cli_version, sessions.cli_version),
            total_input_tokens = sessions.total_input_tokens + excluded.total_input_tokens,
            total_output_tokens = sessions.total_output_tokens + excluded.total_output_tokens,
            total_cache_read_tokens = sessions.total_cache_read_tokens + excluded.total_cache_read_tokens,
            total_cache_creation_tokens = sessions.total_cache_creation_tokens + excluded.total_cache_creation_tokens,
            total_thinking_tokens = sessions.total_thinking_tokens + excluded.total_thinking_tokens,
            estimated_cost_usd = sessions.estimated_cost_usd + excluded.estimated_cost_usd
        ''', (
            session_id, 'Claude Code', project_path, start_time, git_branch, active_model, cli_version,
            session_input_tokens, session_output_tokens, session_cache_read, session_cache_create,
            session_thinking, session_cost
        ))
        
        for act in activities_to_insert:
            cursor.execute('''
            INSERT OR IGNORE INTO activities (
                session_id, timestamp, content, action_type,
                model, prompt_tokens, completion_tokens, cache_read_tokens,
                cache_creation_tokens, thinking_tokens, cost_usd,
                first_token_latency_ms, stream_duration_ms, tokens_per_sec
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', act)

        for t in tools_to_insert:
            cursor.execute('''
            INSERT INTO tool_executions (session_id, activity_id, tool_name, command, exit_code, duration_ms, stdout_snippet, stderr_snippet, status, timestamp)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', t)

        for h in hotspots_to_insert:
            cursor.execute('''
            INSERT INTO file_hotspots (session_id, project_path, file_path, operation, timestamp)
            VALUES (?, ?, ?, ?, ?)
            ''', h)

        conn.commit()
        conn.close()
        print(f"📥 [Claude Code] Ingested {len(activities_to_insert)} events from {session_id[:8]}")

    return len(activities_to_insert)

# ==============================================================================
# KIMI CODE SINGLE FILE PROCESSOR
# ==============================================================================
def process_kimi_session(wire_file):
    if not os.path.exists(wire_file):
        return 0

    # wire_file is .../sessions/<wd_hash>/<session_id>/agents/main/wire.jsonl
    session_dir = os.path.dirname(os.path.dirname(os.path.dirname(wire_file)))
    state_file = os.path.join(session_dir, "state.json")
    session_id = os.path.basename(session_dir)
    work_dir = "Unknown Kimi Workspace"
    start_time = datetime.now().isoformat()

    if os.path.exists(state_file):
        try:
            with open(state_file, 'r', encoding='utf-8') as sf:
                sdata = json.load(sf)
                session_id = sdata.get("id") or session_id
                work_dir = sdata.get("workDir") or sdata.get("cwd") or work_dir
                start_time = to_iso_timestamp(sdata.get("createdAt") or start_time)
        except Exception:
            pass

    # Fallback to session_index.jsonl if workDir not in state.json
    if work_dir == "Unknown Kimi Workspace":
        index_file = "/data/kimi/session_index.jsonl"
        if os.path.exists(index_file):
            try:
                with open(index_file, 'r', encoding='utf-8') as f:
                    for line in f:
                        if session_id in line:
                            d = json.loads(line)
                            if "workDir" in d:
                                work_dir = d["workDir"]
                                break
            except Exception:
                pass

    work_dir = normalize_project_path(work_dir)

    with offsets_lock:
        offset = file_offsets.get(wire_file, 0)

    try:
        file_size = os.path.getsize(wire_file)
        if offset > file_size:
            offset = 0
    except OSError:
        return 0

    activities_to_insert = []
    tools_to_insert = []
    hotspots_to_insert = []

    session_input_tokens = 0
    session_output_tokens = 0
    session_cache_read = 0
    session_cache_create = 0
    session_cost = 0.0

    try:
        with open(wire_file, 'r', encoding='utf-8') as wf:
            if offset > 0:
                wf.seek(offset)
                
            for line in wf:
                if not line.strip():
                    continue
                try:
                    data = json.loads(line)
                    t = data.get("type")
                    timestamp = to_iso_timestamp(data.get("time") or start_time)
                    
                    if t == "turn.prompt":
                        inputs = data.get("input", [])
                        text_parts = []
                        if isinstance(inputs, list):
                            for inp in inputs:
                                if isinstance(inp, dict) and inp.get("type") == "text":
                                    text_parts.append(inp.get("text", ""))
                                elif isinstance(inp, str):
                                    text_parts.append(inp)
                        elif isinstance(inputs, str):
                            text_parts.append(inputs)
                        content = " ".join(text_parts).strip()
                        if content:
                            activities_to_insert.append((
                                session_id, timestamp, content, "USER_INPUT",
                                None, 0, 0, 0, 0, 0, 0.0, 0, 0, 0.0
                            ))
                            
                    elif t == "context.append_loop_event":
                        ev = data.get("event", {})
                        etype = ev.get("type")
                        
                        if etype == "step.end":
                            usage = ev.get("usage", {})
                            in_other = usage.get("inputOther", 0)
                            out_tok = usage.get("output", 0)
                            cache_read = usage.get("inputCacheRead", 0)
                            cache_create = usage.get("inputCacheCreation", 0)
                            ttft = ev.get("llmFirstTokenLatencyMs", 0)
                            stream_ms = ev.get("llmStreamDurationMs", 0)
                            tok_sec = (out_tok / (stream_ms / 1000.0)) if stream_ms > 0 else 0.0
                            cost_usd, _, _ = calculate_cost_and_savings("k3-256k", in_other, cache_read, cache_create, out_tok)
                            
                            session_input_tokens += in_other
                            session_output_tokens += out_tok
                            session_cache_read += cache_read
                            session_cache_create += cache_create
                            session_cost += cost_usd

                            # If last activity was a planner response without telemetry, enrich it
                            if activities_to_insert and activities_to_insert[-1][3] == "PLANNER_RESPONSE":
                                last = activities_to_insert.pop()
                                activities_to_insert.append((
                                    last[0], last[1], last[2], last[3],
                                    "k3-256k", in_other, out_tok, cache_read,
                                    cache_create, 0, cost_usd, ttft, stream_ms, tok_sec
                                ))

                        elif etype == "content.part":
                            part = ev.get("part", {})
                            if part.get("type") == "text":
                                content = part.get("text", "").strip()
                                if content:
                                    activities_to_insert.append((
                                        session_id, timestamp, content, "PLANNER_RESPONSE",
                                        "k3-256k", 0, 0, 0, 0, 0, 0.0, 0, 0, 0.0
                                    ))
                        elif etype == "tool.call":
                            tname = ev.get("name", "tool")
                            args = ev.get("args", {})
                            disp = ev.get("display", {})
                            cmd = None
                            if tname == "Bash" and "command" in args:
                                cmd = str(args.get("command", "")).strip().replace("\n", " ")
                                content = f"Ran: {cmd[:77]}..." if len(cmd) > 80 else f"Ran: {cmd}"
                            elif tname in ["Read", "Edit", "Write"] and "path" in args:
                                content = f"{tname}: {args.get('path')}"
                            else:
                                content = f"Tool: {tname}"
                            
                            tools_to_insert.append((
                                session_id, None, tname, cmd, 0, 0, None, None, 'success', timestamp
                            ))

                            if disp.get("kind") == "file_io" or tname in ["Read", "Edit", "Write"]:
                                fpath = disp.get("path") or args.get("path")
                                if fpath:
                                    hotspots_to_insert.append((
                                        session_id, work_dir, str(fpath),
                                        disp.get("operation") or tname.lower(),
                                        timestamp
                                    ))

                            activities_to_insert.append((
                                session_id, timestamp, content, "PLANNER_RESPONSE",
                                "k3-256k", 0, 0, 0, 0, 0, 0.0, 0, 0, 0.0
                            ))
                except json.JSONDecodeError:
                    continue
            new_offset = wf.tell()
    except Exception as e:
        print(f"Error reading Kimi wire {wire_file}: {e}")
        return 0

    with offsets_lock:
        file_offsets[wire_file] = new_offset

    if activities_to_insert:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute('''
        INSERT INTO sessions (
            id, agent_type, project_path, start_time, model,
            total_input_tokens, total_output_tokens, total_cache_read_tokens,
            total_cache_creation_tokens, estimated_cost_usd
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET
            project_path=excluded.project_path,
            total_input_tokens = sessions.total_input_tokens + excluded.total_input_tokens,
            total_output_tokens = sessions.total_output_tokens + excluded.total_output_tokens,
            total_cache_read_tokens = sessions.total_cache_read_tokens + excluded.total_cache_read_tokens,
            total_cache_creation_tokens = sessions.total_cache_creation_tokens + excluded.total_cache_creation_tokens,
            estimated_cost_usd = sessions.estimated_cost_usd + excluded.estimated_cost_usd
        ''', (
            session_id, 'Kimi Code', work_dir, start_time, 'k3-256k',
            session_input_tokens, session_output_tokens, session_cache_read,
            session_cache_create, session_cost
        ))
        
        for act in activities_to_insert:
            cursor.execute('''
            INSERT OR IGNORE INTO activities (
                session_id, timestamp, content, action_type,
                model, prompt_tokens, completion_tokens, cache_read_tokens,
                cache_creation_tokens, thinking_tokens, cost_usd,
                first_token_latency_ms, stream_duration_ms, tokens_per_sec
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', act)

        for t in tools_to_insert:
            cursor.execute('''
            INSERT INTO tool_executions (session_id, activity_id, tool_name, command, exit_code, duration_ms, stdout_snippet, stderr_snippet, status, timestamp)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', t)

        for h in hotspots_to_insert:
            cursor.execute('''
            INSERT INTO file_hotspots (session_id, project_path, file_path, operation, timestamp)
            VALUES (?, ?, ?, ?, ?)
            ''', h)

        conn.commit()
        conn.close()
        print(f"📥 [Kimi Code] Ingested {len(activities_to_insert)} events from {session_id[:8]}")

    return len(activities_to_insert)

# ==============================================================================
# INITIAL HYDRATION / SCAN
# ==============================================================================
def initial_sync():
    """Performs an initial scan of all existing logs to hydrate database and file offsets."""
    print("🚀 Running initial sync of agent logs...")
    
    # Agy
    agy_base = "/data/agy/brain"
    if os.path.exists(agy_base):
        for sid in os.listdir(agy_base):
            tp = os.path.join(agy_base, sid, ".system_generated", "logs", "transcript.jsonl")
            if os.path.exists(tp):
                process_agy_file(tp, sid)
                
    # Claude Code
    claude_base = "/data/claude-code/projects"
    if os.path.exists(claude_base):
        for root, dirs, files in os.walk(claude_base):
            for f in files:
                if f.endswith(".jsonl") and not f.startswith("agent-"):
                    process_claude_file(os.path.join(root, f))
                    
    # Kimi Code
    kimi_base = "/data/kimi/sessions"
    if os.path.exists(kimi_base):
        import glob
        for wf in glob.glob(os.path.join(kimi_base, "*", "*", "agents", "main", "wire.jsonl")):
            process_kimi_session(wf)
            
    print(f"✅ Initial sync complete. Tracking {len(file_offsets)} active log streams.")

# ==============================================================================
# WATCHDOG EVENT HANDLER
# ==============================================================================
class AgentLogEventHandler(FileSystemEventHandler):
    """Watches agent directories and routes file changes in real-time."""

    def on_modified(self, event):
        if event.is_directory:
            return
        self._route_event(event.src_path)

    def on_created(self, event):
        if event.is_directory:
            return
        self._route_event(event.src_path)

    def _route_event(self, path):
        # Agy: .../brain/<session_id>/.system_generated/logs/transcript.jsonl
        if path.endswith("transcript.jsonl") and "/brain/" in path:
            parts = path.split("/brain/")
            if len(parts) > 1:
                session_id = parts[1].split("/")[0]
                process_agy_file(path, session_id)
                
        # Claude Code: .../projects/.../*.jsonl
        elif path.endswith(".jsonl") and "/projects/" in path and not os.path.basename(path).startswith("agent-"):
            process_claude_file(path)
            
        # Kimi Code: .../sessions/.../agents/main/wire.jsonl
        elif path.endswith("wire.jsonl") and "/agents/main/" in path:
            process_kimi_session(path)

# ==============================================================================
# MAIN ENTRYPOINT
# ==============================================================================
def main():
    print("🚀 Real-Time Agent Activity Watcher starting...")
    os.makedirs("/app/db", exist_ok=True)
    init_db()
    
    # Run initial sync to load existing data and position offsets
    initial_sync()
    
    # Start File Watcher
    observer = Observer()
    handler = AgentLogEventHandler()
    
    watch_dirs = [
        ("/data/claude-code/projects", "Claude Code"),
        ("/data/kimi/sessions", "Kimi Code"),
        ("/data/agy/brain", "Agy CLI")
    ]
    
    scheduled_count = 0
    for path, name in watch_dirs:
        if os.path.exists(path):
            observer.schedule(handler, path, recursive=True)
            print(f"👀 Real-time watcher active for {name} ({path})")
            scheduled_count += 1
        else:
            print(f"⚠️ Watch directory missing: {path}")

    if scheduled_count > 0:
        observer.start()
        print(f"⚡ Inotify event loop running with {scheduled_count} active watches.")
    else:
        print("❌ No watch directories found!")
        return

    try:
        # Periodic light heartbeat every 10 minutes as a safety net
        while True:
            time.sleep(600)
            print("💓 Collector heartbeat: watches active and healthy.")
    except KeyboardInterrupt:
        observer.stop()
    observer.join()

if __name__ == "__main__":
    main()
