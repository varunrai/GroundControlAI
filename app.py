from fastapi import FastAPI, Request
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from typing import Optional
import sqlite3
import os
from normalizer import normalize_project_path, get_project_display_name

app = FastAPI()
if os.path.exists("assets"):
    app.mount("/assets", StaticFiles(directory="assets"), name="assets")

templates = Jinja2Templates(directory="templates")
DB_PATH = "/app/db/activity.db"

def get_db():
    conn = sqlite3.connect(DB_PATH, timeout=30.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=30000;")
    return conn

@app.get("/")
async def read_root(
    request: Request,
    agent: Optional[str] = None,
    q: Optional[str] = None,
    limit: int = 5000
):
    if not os.path.exists(DB_PATH):
        return templates.TemplateResponse(
            request=request,
            name="index.html",
            context={
                "projects": {},
                "stats": [],
                "cockpit_stats": {},
                "selected_agent": agent,
                "query": q,
                "error": "Database not found yet."
            }
        )
        
    conn = get_db()
    cursor = conn.cursor()
    
    user_home = os.path.expanduser("~")
    # Base query
    query_conditions = [
        "s.project_path != ''",
        "s.project_path != 'Unknown'",
        "s.project_path != 'Unknown Kimi Workspace'",
        "s.project_path NOT LIKE '%/Downloads%'",
        f"s.project_path NOT IN ('{user_home}', '{user_home}/', '/home/developer', '~')",
        "s.project_path NOT LIKE '/run/media%'"
    ]
    params = []

    if agent and agent != "All":
        query_conditions.append("s.agent_type = ?")
        params.append(agent)

    if q:
        query_conditions.append("(a.content LIKE ? OR s.project_path LIKE ?)")
        params.extend([f"%{q}%", f"%{q}%"])

    where_clause = " AND ".join(query_conditions)

    # 1. Activities per project (ranked partition)
    sql = f'''
        WITH ranked_activities AS (
            SELECT 
                a.id as activity_id,
                a.session_id,
                a.timestamp, 
                a.content, 
                a.action_type, 
                a.model,
                a.prompt_tokens,
                a.completion_tokens,
                a.cache_read_tokens,
                a.thinking_tokens,
                a.cost_usd,
                a.first_token_latency_ms,
                a.stream_duration_ms,
                a.tokens_per_sec,
                s.agent_type, 
                s.project_path,
                ROW_NUMBER() OVER(PARTITION BY s.project_path ORDER BY a.timestamp DESC) as rn
            FROM activities a
            JOIN sessions s ON a.session_id = s.id
            WHERE {where_clause}
        )
        SELECT *
        FROM ranked_activities
        WHERE rn <= 25
        ORDER BY project_path, timestamp DESC
    '''
    cursor.execute(sql, params)
    raw_activities = cursor.fetchall()
    
    # Organize by project
    projects = {}
    for row in raw_activities:
        proj_path = normalize_project_path(row['project_path'])
        proj_name = get_project_display_name(proj_path)
        
        if proj_name not in projects:
            projects[proj_name] = {
                "name": proj_name,
                "path": proj_path,
                "agents": set(),
                "activities": [],
                "tools": [],
                "hotspots": [],
                "branches": set(),
                "models": set(),
                "total_cost": 0.0,
                "total_tokens": 0
            }
            
        projects[proj_name]["activities"].append(row)
        projects[proj_name]["agents"].add(row['agent_type'])
        if row['model']:
            projects[proj_name]["models"].add(row['model'])
        projects[proj_name]["total_cost"] += (row['cost_usd'] or 0.0)
        projects[proj_name]["total_tokens"] += ((row['prompt_tokens'] or 0) + (row['completion_tokens'] or 0))

    # Populate tools, hotspots, and metadata for each project
    for p in projects.values():
        p["agents"] = list(p["agents"])
        p["models"] = list(p["models"])
        p["total_cost"] = round(p["total_cost"], 4)

        # Recent tool executions
        cursor.execute('''
            SELECT t.tool_name, t.command, t.exit_code, t.duration_ms, t.status, t.timestamp
            FROM tool_executions t
            JOIN sessions s ON t.session_id = s.id
            WHERE s.project_path = ? OR s.project_path LIKE ?
            ORDER BY t.timestamp DESC
            LIMIT 15
        ''', (p["path"], p["path"] + "/%"))
        p["tools"] = cursor.fetchall()

        # File Hotspots
        cursor.execute('''
            SELECT file_path, operation, COUNT(*) as touch_count
            FROM file_hotspots
            WHERE project_path = ? OR project_path LIKE ?
            GROUP BY file_path, operation
            ORDER BY touch_count DESC
            LIMIT 5
        ''', (p["path"], p["path"] + "/%"))
        p["hotspots"] = cursor.fetchall()

    # 2. Global Cockpit Telemetry
    cursor.execute('''
        SELECT 
            COALESCE(SUM(cost_usd), 0.0) as total_spend,
            COALESCE(SUM(prompt_tokens), 0) as total_prompt_tokens,
            COALESCE(SUM(completion_tokens), 0) as total_completion_tokens,
            COALESCE(SUM(cache_read_tokens), 0) as total_cache_read_tokens,
            COALESCE(SUM(cache_creation_tokens), 0) as total_cache_creation_tokens,
            COALESCE(SUM(thinking_tokens), 0) as total_thinking_tokens
        FROM activities
    ''')
    token_stats = cursor.fetchone()

    total_spend = round(token_stats['total_spend'], 2)
    prompt_toks = token_stats['total_prompt_tokens']
    cache_read_toks = token_stats['total_cache_read_tokens']
    cache_creation_toks = token_stats['total_cache_creation_tokens']
    completion_toks = token_stats['total_completion_tokens']
    thinking_toks = token_stats['total_thinking_tokens']

    total_in = prompt_toks + cache_read_toks
    cache_hit_pct = round((cache_read_toks / total_in * 100.0), 1) if total_in > 0 else 0.0
    # Estimated cache savings: $2.70 saved per 1M cached read tokens
    cache_savings = round((cache_read_toks / 1_000_000.0) * 2.70, 2)

    # Latency & Throughput
    cursor.execute('''
        SELECT 
            COALESCE(AVG(first_token_latency_ms), 0) as avg_ttft,
            COALESCE(AVG(tokens_per_sec), 0.0) as avg_speed
        FROM activities
        WHERE first_token_latency_ms > 0
    ''')
    latency_stats = cursor.fetchone()
    avg_ttft = int(latency_stats['avg_ttft']) if latency_stats else 0
    avg_speed = round(latency_stats['avg_speed'], 1) if latency_stats else 0.0

    # SRE Command Reliability
    cursor.execute('''
        SELECT 
            COUNT(*) as total_runs,
            COALESCE(SUM(CASE WHEN exit_code = 0 THEN 1 ELSE 0 END), 0) as passed_runs,
            COALESCE(SUM(CASE WHEN exit_code != 0 THEN 1 ELSE 0 END), 0) as failed_runs
        FROM tool_executions
    ''')
    sre_stats = cursor.fetchone()
    total_runs = sre_stats['total_runs'] if sre_stats else 0
    passed_runs = sre_stats['passed_runs'] if sre_stats else 0
    sre_pass_rate = round((passed_runs / total_runs * 100.0), 1) if total_runs > 0 else 100.0

    # Fleet workload split
    cursor.execute('''
        SELECT s.agent_type, COUNT(DISTINCT s.id) as session_count, COUNT(a.id) as activity_count 
        FROM sessions s
        LEFT JOIN activities a ON s.id = a.session_id
        GROUP BY s.agent_type
    ''')
    stats = cursor.fetchall()
    
    total_activities = sum(row['activity_count'] for row in stats) or 1
    fleet_split = []
    for row in stats:
        pct = round((row['activity_count'] / total_activities) * 100.0, 1)
        fleet_split.append({
            "agent_type": row['agent_type'],
            "session_count": row['session_count'],
            "activity_count": row['activity_count'],
            "percentage": pct
        })

    cockpit_stats = {
        "total_spend": total_spend,
        "cache_savings": cache_savings,
        "cache_hit_pct": cache_hit_pct,
        "prompt_tokens": prompt_toks,
        "completion_tokens": completion_toks,
        "cache_read_tokens": cache_read_toks,
        "thinking_tokens": thinking_toks,
        "avg_ttft_ms": avg_ttft,
        "avg_speed": avg_speed,
        "total_commands": total_runs,
        "passed_commands": passed_runs,
        "failed_commands": sre_stats['failed_runs'] if sre_stats else 0,
        "sre_pass_rate": sre_pass_rate,
        "fleet_split": fleet_split
    }

    conn.close()
    
    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={
            "projects": projects, 
            "stats": stats,
            "cockpit_stats": cockpit_stats,
            "selected_agent": agent,
            "query": q
        }
    )
