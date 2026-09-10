# Contributing to GroundControlAI

Thank you for your interest in contributing! Whether you are adding support for a new AI agent (e.g. Cursor, OpenClaw, Codex), optimizing database queries, refining the UI, or writing tests, we welcome your contributions.

---

## 🧭 Code of Conduct

We are committed to providing a welcoming, inclusive, and harassment-free environment for everyone. Please be respectful, constructive, and collaborative in all communications.

---

## 🛠️ Development Setup

### Prerequisites

- **Python 3.11+**
- **Docker & Docker Compose** (optional, recommended for production daemon)
- **uv** (recommended for blazing fast virtualenvs and dependency management)

### Local Environment Setup

1. **Clone the repository**:
   ```bash
   git clone https://github.com/varunrai/GroundControlAI.git
   cd GroundControlAI
   ```

2. **Install dependencies**:
   Using `uv` (fastest):
   ```bash
   uv venv
   source .venv/bin/activate
   uv pip install -r requirements.txt pytest httpx
   ```
   Or standard `pip`:
   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   pip install -r requirements.txt pytest httpx
   ```

3. **Run database migrations**:
   ```bash
   python3 migrations.py
   ```

4. **Run the test suite**:
   ```bash
   pytest tests/ -v
   ```

5. **Start the Web Cockpit locally**:
   ```bash
   uvicorn app:app --reload --port 8080
   ```
   Open [http://localhost:8080](http://localhost:8080) in your browser.

---

## 🏗️ Architecture & Adding New Agent Parsers

The cockpit follows a decoupled event-driven architecture:

```
[Agent Log Files] ──(watchdog Inotify)──> [collector.py] ──(sqlite3 WAL)──> [activity.db] ──(FastAPI)──> [UI Dashboard]
```

### Adding a New Agent Collector

To add support for a new AI agent tool:
1. **Locate raw logs**: Find where the agent logs session events (e.g., JSON Lines, SQLite, or plain text).
2. **Implement file processor in `collector.py`**:
   - Track byte offsets with `file_offsets` so only new lines are parsed on file changes.
   - Extract timestamps, prompt/completion tokens, cache read tokens, and model name.
   - Map tool executions (`tool_executions`) with command line arguments, exit codes, and status.
   - Map file touches (`file_hotspots`) with operation type (`read`, `write`, `edit`).
   - Normalize the working directory using `normalizer.normalize_project_path()`.
3. **Register directory in `collector.py:watch_dirs`**:
   - Add the target log path to the Inotify watcher event loop.
4. **Add unit tests**:
   - Add parser test cases in `tests/test_collector_telemetry.py`.

---

## 🧪 Testing Guidelines

We enforce test-driven development and strict test quality. All pull requests must pass the test suite.

Run all tests:
```bash
PYTHONPATH=. pytest tests/ -v
```

Key test files:
- `tests/test_api_cockpit.py`: FastAPI routes, template rendering, and telemetry aggregations.
- `tests/test_collector_telemetry.py`: Ingest parsers for Claude Code, Kimi Code, and Agy.
- `tests/test_migration.py`: SQLite schema migrations and index validation.
- `tests/test_normalizer.py`: Canonical repository path normalization for subfolders and worktrees.
- `tests/test_pricing.py`: Model token pricing and prompt caching discount calculations.

---

## 🎨 UI Guidelines

- **No Heavy Build Pipelines**: We use **Tailwind CSS CDN** and **Alpine.js CDN** directly in `templates/index.html`. Do not introduce Webpack, Vite, or Node.js runtime dependencies unless strictly agreed upon in an issue proposal.
- **Cyber-Cockpit Aesthetic**: Maintain the dark slate theme (`bg-slate-900`, `border-slate-750`), crisp high-contrast telemetry metrics, and clear distinction between user input and agent tool traces.

---

## 📋 Pull Request Process

1. **Open an Issue first**: Discuss significant feature additions or architectural changes before writing code.
2. **Create a descriptive feature branch**:
   ```bash
   git checkout -b feat/support-cursor-agent
   ```
3. **Write tests**: Ensure tests cover new parsers or UI routes.
4. **Run linters and tests**: Ensure zero test regressions.
5. **Submit PR**: Provide a clear description of changes, screenshots/terminal logs of verification, and linked issues.

---

## 📄 License

By contributing to GroundControlAI, you agree that your contributions will be licensed under the project's [MIT License](LICENSE).
