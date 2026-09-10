import os
import re
from typing import Optional

# Dynamic registry of discovered repository roots (repo_name -> canonical_project_path)
KNOWN_PROJECTS: dict[str, str] = {}
KNOWN_CONTAINERS: set[str] = set()

CATEGORY_FOLDERS = {"ai", "ml", "work", "personal", "clients", "oss", "experiments", "tests"}
SYSTEM_ROOT_DIRS = {"tmp", "run", "var", "etc", "usr", "mnt", "proc", "sys", "dev"}
COMMON_CONTAINER_NAMES = {
    "sources", "projects", "workspace", "workspaces", "code", "repos",
    "repositories", "dev", "development", "src", "git", "ghq", "sites"
}

def _find_root_on_disk(path: str) -> Optional[str]:
    """Walks upwards from a directory to detect the authoritative project root using VCS or manifests."""
    try:
        curr = os.path.abspath(path)
        if not os.path.isdir(curr):
            curr = os.path.dirname(curr)
            
        manifest_candidate = None
        while curr and curr != os.path.dirname(curr):
            git_entry = os.path.join(curr, ".git")
            if os.path.exists(git_entry):
                if os.path.isfile(git_entry):
                    # Git worktree pointer file
                    try:
                        with open(git_entry, "r", encoding="utf-8") as f:
                            txt = f.read().strip()
                        if txt.startswith("gitdir:"):
                            gitdir = txt.split("gitdir:", 1)[1].strip()
                            if "/.git/worktrees/" in gitdir:
                                main_repo = gitdir.split("/.git/worktrees/")[0]
                                if os.path.isdir(main_repo):
                                    return os.path.abspath(main_repo)
                    except Exception:
                        pass
                return curr
                
            if not manifest_candidate:
                for marker in (".obsidian", ".logseq", "pyproject.toml", "package.json", "Cargo.toml", "go.mod", "requirements.txt", "Makefile"):
                    if os.path.exists(os.path.join(curr, marker)):
                        manifest_candidate = curr
                        break
                        
            curr = os.path.dirname(curr)
            
        return manifest_candidate
    except Exception:
        return None

def normalize_project_path(raw_path: str) -> str:
    """
    Normalizes workspace / working directory paths to the canonical project root
    dynamically without hardcoding directory names.
    """
    if not raw_path:
        return "Unknown"
    p = raw_path.strip().replace("\\", "/")

    # 1. Authoritative check: If path exists on disk, inspect VCS and project markers
    if os.path.exists(p):
        disk_root = _find_root_on_disk(p)
        if disk_root:
            base = os.path.basename(disk_root)
            KNOWN_PROJECTS[base] = disk_root
            return disk_root

    # 2. Ephemeral Worktrees pattern (e.g. .ao/data/worktrees/<repo>/..., .git/worktrees/<repo>/...)
    m = re.search(r'worktrees/([^/]+)', p)
    if m:
        repo = m.group(1)
        prefix = p.split('/.ao/')[0] if '/.ao/' in p else (p.split('/worktrees/')[0] if '/worktrees/' in p else os.path.expanduser('~'))
        if not prefix or prefix == '.':
            prefix = os.path.expanduser('~')
            
        # Check known projects cache
        if repo in KNOWN_PROJECTS:
            known_path = KNOWN_PROJECTS[repo]
            rel = known_path.lstrip('/')
            parts = rel.split('/')
            if len(parts) >= 3:
                container = parts[2] if parts[0] in ('home', 'Users') else parts[0]
                return f"{prefix}/{container}/{repo}"
            return f"{prefix}/{repo}"
            
        # Check known containers
        for c in KNOWN_CONTAINERS:
            return f"{prefix}/{c}/{repo}"
            
        return f"{prefix}/{repo}"

    # 3. Structural heuristic for non-disk / container / remote paths
    norm = os.path.normpath(p)
    parts = [seg for seg in norm.strip("/").split("/") if seg]

    # Handle system mount / temp paths
    if parts and parts[0] in SYSTEM_ROOT_DIRS:
        if len(parts) <= 3:
            return norm

    # Strip hidden directories inside project (e.g. .backpass, .github)
    cut_idx = -1
    for idx, seg in enumerate(parts):
        # Ignore leading dotfiles in user home
        if idx > 2 and seg.startswith("."):
            cut_idx = idx
            break
    if cut_idx != -1:
        parts = parts[:cut_idx]

    # Check if any segment is a common container folder (e.g. sources, projects, workspace, etc.)
    for i, seg in enumerate(parts):
        if seg.lower() in COMMON_CONTAINER_NAMES:
            if i + 1 < len(parts):
                # Check for category subfolder (e.g. ai/mail-agent)
                if parts[i + 1].lower() in CATEGORY_FOLDERS or len(parts[i + 1]) <= 2:
                    if i + 2 < len(parts):
                        res = "/" + "/".join(parts[: i + 3])
                        KNOWN_PROJECTS[os.path.basename(res)] = res
                        return res
                res = "/" + "/".join(parts[: i + 2])
                KNOWN_PROJECTS[os.path.basename(res)] = res
                return res

    # Generic user home paths (/home/<user>/<custom_folder>/<project>/...)
    if len(parts) >= 4 and parts[0] in ("home", "Users"):
        if parts[3].lower() in CATEGORY_FOLDERS or len(parts[3]) <= 2:
            if len(parts) >= 5:
                res = "/" + "/".join(parts[:5])
                KNOWN_PROJECTS[os.path.basename(res)] = res
                return res
        res = "/" + "/".join(parts[:4])
        KNOWN_PROJECTS[os.path.basename(res)] = res
        return res

    return norm

def get_project_display_name(project_path: str) -> str:
    """Returns clean human-readable project title."""
    if not project_path:
        return "Unknown"
    p = normalize_project_path(project_path)
    if "/" in p:
        base = os.path.basename(p.rstrip("/"))
        return base or p
    return p
