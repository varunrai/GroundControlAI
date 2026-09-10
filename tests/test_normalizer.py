from normalizer import normalize_project_path, get_project_display_name
import os

def test_normalize_expens_aify_subdirs():
    assert normalize_project_path("/home/developer/Sources/finance-core/infrastructure") == "/home/developer/Sources/finance-core"
    assert normalize_project_path("/home/developer/Sources/finance-core/.backpass/synthesis") == "/home/developer/Sources/finance-core"
    prefix = os.path.expanduser("~")
    assert normalize_project_path(f"{prefix}/.ao/data/worktrees/finance-core/orchestrator/finance-core-orchestrator") == f"{prefix}/Sources/finance-core"
    assert get_project_display_name("/home/developer/Sources/finance-core/infrastructure") == "finance-core"

def test_normalize_knowledge_vault_subdirs():
    assert normalize_project_path("/home/developer/Sources/knowledge-vault/AI/Work/Weekly") == "/home/developer/Sources/knowledge-vault"
    assert normalize_project_path("/home/developer/Sources/knowledge-vault/AI/ONTAP Ideas") == "/home/developer/Sources/knowledge-vault"
    assert get_project_display_name("/home/developer/Sources/knowledge-vault/AI/Work/Weekly") == "knowledge-vault"

def test_normalize_other_projects():
    assert normalize_project_path("/home/developer/Sources/ai/mail-agent") == "/home/developer/Sources/ai/mail-agent"
    assert get_project_display_name("/home/developer/Sources/ai/mail-agent") == "mail-agent"
    assert normalize_project_path("/home/developer/Downloads") == "/home/developer/Downloads"

def test_normalize_arbitrary_containers_without_sources():
    # Projects container
    assert normalize_project_path("/home/developer/Projects/payment-engine/src/api") == "/home/developer/Projects/payment-engine"
    assert get_project_display_name("/home/developer/Projects/payment-engine/src/api") == "payment-engine"

    # Workspace container (macOS / Linux)
    assert normalize_project_path("/Users/alice/workspace/mobile-app/android/app") == "/Users/alice/workspace/mobile-app"
    assert get_project_display_name("/Users/alice/workspace/mobile-app/android/app") == "mobile-app"

    # Code container
    assert normalize_project_path("/home/bob/code/engine/core/internals") == "/home/bob/code/engine"

    # Root-level Docker workspace
    assert normalize_project_path("/workspace/team-repo/services/auth") == "/workspace/team-repo"

def test_normalize_on_disk_repo_root():
    # If a real directory with .git exists, it should resolve to repo root dynamically
    current_dir = os.path.dirname(os.path.abspath(__file__))
    repo_root = os.path.dirname(current_dir)
    templates_dir = os.path.join(repo_root, "templates")
    assert normalize_project_path(templates_dir) == repo_root

