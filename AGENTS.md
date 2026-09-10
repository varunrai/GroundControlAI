# GroundControlAI — Agent Guidelines & Instructions

This file guides AI coding agents (Claude Code, Kimi Code, Agy CLI, Antigravity) working on the **GroundControlAI** project.

## Core Rules & Guardrails
1. **Zero PII Exposure**:
   - Never commit or log personal usernames, home directory paths, private IP addresses, or GitHub tokens.
   - All demo mockups, screenshots, and test datasets must use sanitized placeholders (`developer`, `~/projects/`, `10.0.0.12`, `ghp_mock_token_redacted`, `finance-core`, `audit-sentinel`, etc.).
2. **Git Workflow**:
   - Always work on feature branches (e.g. `feat/xyz` or `fix/abc`).
   - Always write or update corresponding pytest tests before submitting changes.
   - Ensure all unit tests pass: `PYTHONPATH=. pytest tests/ -v`.
3. **Database & Concurrency**:
   - SQLite operates in WAL (Write-Ahead Logging) mode.
   - Any query or update must handle potential busy locks using `busy_timeout=30000`.
   - Never commit database files (`activity.db`, `activity.db-wal`, `activity.db-shm`) to version control.
4. **Daemon Efficiency**:
   - Telemetry collection relies on Linux `inotify` (via Python `watchdog`).
   - Incremental reads must track byte offsets (`f.tell()`) to keep CPU usage at 0.00% idle.
   - Avoid polling loops or repetitive disk reads.

## Architecture Links
- [[Home|Project Overview]]
- [[Architecture|Technical Architecture]]
- [[PRD|Product Requirements Document]]
- [[Roadmap|Milestones & Feature Roadmap]]
- [[superpowers/specs/2026-09-10-agent-observability-cockpit-design|Cockpit Design Spec]]
- [[superpowers/plans/2026-09-10-agent-observability-cockpit|Implementation Plan]]
