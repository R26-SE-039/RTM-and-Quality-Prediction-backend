import os


class UnsupportedLanguage(Exception):
    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


PYTHON_MARKERS = ["requirements.txt", "pyproject.toml", "setup.py", "setup.cfg", "Pipfile"]
JAVA_MARKERS = ["pom.xml", "build.gradle", "build.gradle.kts", "settings.gradle", "settings.gradle.kts"]
IGNORE_DIRS = {"node_modules", ".git", "venv", ".venv", "__pycache__", "dist", "build", ".next", "coverage"}


def _immediate_subdirs(repo_dir: str) -> list[str]:
    try:
        entries = os.listdir(repo_dir)
    except OSError:
        return []
    return [
        os.path.join(repo_dir, d)
        for d in entries
        if not d.startswith(".") and d not in IGNORE_DIRS and os.path.isdir(os.path.join(repo_dir, d))
    ]


def find_project_dirs(repo_dir: str) -> dict[str, list[str]]:
    """Scans the repo root and one level of subdirectories for recognizable
    project roots, so a typical MERN-style layout (client/ + server/, each
    with their own package.json) or a Python-service-plus-JS-frontend
    monorepo is detected as multiple projects rather than requiring one
    stack at the repo root.

    Returns {"python": [...dirs], "javascript": [...dirs], "java": [...dirs]}.
    """
    candidates = [repo_dir] + _immediate_subdirs(repo_dir)
    found: dict[str, list[str]] = {"python": [], "javascript": [], "java": []}

    for d in candidates:
        try:
            entries = os.listdir(d)
        except OSError:
            continue
        if "package.json" in entries:
            found["javascript"].append(d)
        elif any(marker in entries for marker in PYTHON_MARKERS):
            found["python"].append(d)
        elif any(marker in entries for marker in JAVA_MARKERS):
            found["java"].append(d)

    return found
