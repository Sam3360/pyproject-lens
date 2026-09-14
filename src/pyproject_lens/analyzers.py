"""The intentionally small, dependency-free project checks."""

from __future__ import annotations

import ast
from fnmatch import fnmatch
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - Python 3.9/3.10
    import tomli as tomllib  # type: ignore[no-redef]

from .models import Report, Section

SKIP_DIRS = {".git", ".venv", "venv", "__pycache__", "build", "dist", ".tox", ".mypy_cache"}
STDLIB = set(getattr(sys, "stdlib_module_names", ()))
IMPORT_NAMES = {
    "PIL": "pillow",
    "bs4": "beautifulsoup4",
    "cv2": "opencv-python",
    "dateutil": "python-dateutil",
    "dotenv": "python-dotenv",
    "sklearn": "scikit-learn",
    "yaml": "pyyaml",
}


def _python_files(root: Path) -> list[Path]:
    return [path for path in root.rglob("*.py") if not any(part in SKIP_DIRS for part in path.parts)]


def _source_files(root: Path, files: list[Path]) -> list[Path]:
    """Return project code, leaving test-only imports out of dependency checks."""
    return [path for path in files if "tests" not in path.relative_to(root).parts]


def _read_toml(path: Path) -> dict[str, Any]:
    try:
        with path.open("rb") as handle:
            return tomllib.load(handle)
    except (OSError, tomllib.TOMLDecodeError):
        return {}


def _project(config: dict[str, Any]) -> dict[str, Any]:
    data = config.get("project", {})
    return data if isinstance(data, dict) else {}


def _imports(root: Path, files: list[Path]) -> dict[str, str]:
    found: dict[str, str] = {}
    for file in files:
        try:
            tree = ast.parse(file.read_text(encoding="utf-8"), filename=str(file))
        except (OSError, UnicodeDecodeError, SyntaxError):
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for name in node.names:
                    top = name.name.split(".")[0]
                    found.setdefault(top, f"{file.relative_to(root).as_posix()}:{node.lineno}")
            elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
                top = node.module.split(".")[0]
                found.setdefault(top, f"{file.relative_to(root).as_posix()}:{node.lineno}")
    return found


def _distribution_name(value: str) -> str:
    return re.split(r"[<>=!~;[ ]", value, maxsplit=1)[0].lower().replace("_", "-")


def _packaging(root: Path, config: dict[str, Any]) -> Section:
    section = Section("Packaging")
    pyproject = root / "pyproject.toml"
    project = _project(config)
    if not pyproject.exists():
        section.score = 30
        section.add("warning", "No pyproject.toml found.", "Add one to describe how your project is built.")
        return section
    if not config:
        section.score = 45
        section.add("error", "pyproject.toml could not be read.", "Check its TOML syntax.", "pyproject.toml")
        return section
    if not project.get("name"):
        section.score -= 20
        section.add("warning", "Project name is missing.", "Set project.name in pyproject.toml.", "pyproject.toml")
    if not project.get("requires-python"):
        section.score -= 15
        section.add("warning", "Supported Python versions are not declared.", "Set project.requires-python.", "pyproject.toml")
    if not (root / "README.md").exists() and not project.get("readme"):
        section.score -= 15
        section.add("warning", "No README was found.", "Add a short README with install and usage instructions.")
    return section


def _dependencies(root: Path, config: dict[str, Any], files: list[Path]) -> Section:
    section = Section("Dependencies")
    deps = _project(config).get("dependencies", [])
    declared = {_distribution_name(item) for item in deps if isinstance(item, str)}
    imports = _imports(root, files)
    local = {path.stem for path in files}
    for file in files:
        try:
            relative = file.relative_to(root)
        except ValueError:
            continue
        local.update(part for part in relative.parts[:-1] if part not in {"src", "tests"})
    missing = sorted(name for name in imports if name not in STDLIB and name not in local and IMPORT_NAMES.get(name, name.replace("_", "-")).lower() not in declared)
    if missing:
        section.score -= min(45, 10 * len(missing))
        for name in missing[:8]:
            section.add("warning", f"'{name}' is imported but not declared.", "Add it to project.dependencies if it is a runtime dependency.", imports[name])
    if (root / "requirements.txt").exists() and not declared:
        section.score -= 10
        section.add("info", "requirements.txt exists but project.dependencies is empty.", "Consider keeping runtime dependencies in pyproject.toml.")
    return section


def _compatibility(config: dict[str, Any], files: list[Path]) -> Section:
    section = Section("Python compatibility")
    requires = _project(config).get("requires-python", "")
    requires = requires if isinstance(requires, str) else ""
    uses_match = False
    for file in files:
        try:
            uses_match |= any(isinstance(node, ast.Match) for node in ast.walk(ast.parse(file.read_text(encoding="utf-8"))))
        except (OSError, UnicodeDecodeError, SyntaxError):
            continue
    if uses_match and re.search(r">=3\.(?:[0-9]|10)\b", requires) and not re.search(r">=3\.(?:1[0-9]|[2-9][0-9])\b", requires):
        section.score = 60
        section.add("warning", "match/case syntax needs Python 3.10+.", "Raise requires-python to >=3.10 or avoid match/case.")
    elif not requires:
        section.score = 80
        section.add("info", "Compatibility cannot be checked without requires-python.", "Declare supported Python versions in pyproject.toml.")
    return section


def _structure(root: Path, files: list[Path]) -> Section:
    section = Section("Project structure")
    source_root = root / "src"
    packages = [path for path in (source_root if source_root.is_dir() else root).iterdir() if path.is_dir() and (path / "__init__.py").exists()]
    if source_root.is_dir() and not packages:
        section.score -= 25
        section.add("warning", "src/ exists but no package was detected.", "Put your package in src/ with an __init__.py file.", "src")
    top_level = [path for path in files if path.parent == root and path.name not in {"setup.py", "conftest.py"}]
    if len(top_level) > 6:
        section.score -= 15
        section.add("info", f"{len(top_level)} Python files live at the project root.", "Consider grouping application code into a package.")
    tests = root / "tests"
    if not tests.exists():
        section.score -= 20
        section.add("warning", "No tests/ directory found.", "Start with a small tests/ directory for important behavior.")
    return section


def _testing(root: Path, files: list[Path]) -> Section:
    section = Section("Testing")
    test_files = [path for path in files if "tests" in path.relative_to(root).parts or path.name.startswith("test_") or path.name.endswith("_test.py")]
    source_files = [path for path in _source_files(root, files) if path.name != "__init__.py"]
    if not test_files:
        section.score = 55
        section.add("warning", "No test files detected.", "Add a few test_*.py files for the code users rely on.")
        return section
    if not (root / "tests").is_dir():
        section.score -= 10
        section.add("info", "Tests were found outside a tests/ directory.", "A tests/ directory makes the project easier to navigate.")
    if source_files and len(test_files) < max(1, len(source_files) // 3):
        section.score -= 20
        section.add("info", f"{len(test_files)} test file(s) for {len(source_files)} source file(s).", "This is not coverage; consider adding tests around the most important modules.")
    return section


SECRET_NAMES = re.compile(r"(?:password|passwd|secret|api[_-]?key|access[_-]?token|private[_-]?key)", re.IGNORECASE)


def _security(root: Path, files: list[Path]) -> Section:
    section = Section("Security")
    for file in _source_files(root, files):
        try:
            tree = ast.parse(file.read_text(encoding="utf-8"), filename=str(file))
        except (OSError, UnicodeDecodeError, SyntaxError):
            continue
        for node in ast.walk(tree):
            if isinstance(node, (ast.Assign, ast.AnnAssign)):
                targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                value = node.value
                names = [target.id for target in targets if isinstance(target, ast.Name)]
                if isinstance(value, ast.Constant) and isinstance(value.value, str) and len(value.value) >= 8 and any(SECRET_NAMES.search(name) for name in names):
                    section.score -= 30
                    section.add("warning", "Possible hard-coded secret detected.", "Move it to an environment variable and rotate it if it is real.", f"{file.relative_to(root)}:{node.lineno}")
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in {"eval", "exec"}:
                section.score -= 20
                section.add("warning", f"{node.func.id}() detected.", "Avoid executing dynamic code unless the input is completely trusted.", f"{file.relative_to(root)}:{node.lineno}")
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr in {"run", "call", "Popen"}:
                if any(keyword.arg == "shell" and isinstance(keyword.value, ast.Constant) and keyword.value.value is True for keyword in node.keywords):
                    section.score -= 15
                    section.add("warning", "subprocess call with shell=True detected.", "Prefer argument lists and validate any input passed to a shell.", f"{file.relative_to(root)}:{node.lineno}")
    env = root / ".env"
    ignore = root / ".gitignore"
    pats = []
    if ignore.exists():
        pats = [line.strip().lstrip("/") for line in ignore.read_text(encoding="utf-8", errors="replace").splitlines() if line.strip() and not line.startswith("#")]
    if env.exists() and not any(fnmatch(".env", pat) for pat in pats):
        section.score -= 15
        section.add("warning", ".env is not clearly ignored.", "Add .env to .gitignore so it does not get committed.", ".env")
    section.score = max(0, section.score)
    return section


def _documentation(root: Path) -> Section:
    section = Section("Documentation")
    readme = root / "README.md"
    if not readme.exists():
        section.score = 45
        section.add("warning", "No README.md found.", "Add a short introduction, install command, and usage example.")
        return section
    text = readme.read_text(encoding="utf-8", errors="replace").lower()
    if not any(word in text for word in ("install", "pip install")):
        section.score -= 20
        section.add("warning", "README has no detected installation instructions.", "Show the shortest install command.", "README.md")
    if not any(word in text for word in ("usage", "quick start", "example")):
        section.score -= 20
        section.add("warning", "README has no detected usage example.", "Show one small command or code example.", "README.md")
    if not any((root / name).exists() for name in ("LICENSE", "LICENSE.md", "LICENSE.txt")):
        section.score -= 15
        section.add("warning", "No license file found.", "Add a license so people know how they may use the project.")
    if not any((root / name).exists() for name in ("CONTRIBUTING.md", "CONTRIBUTING.rst")):
        section.score -= 10
        section.add("info", "No contribution guide found.", "A short CONTRIBUTING.md helps first-time contributors.")
    return section


def _git_health(root: Path) -> Section:
    section = Section("Repository hygiene")
    if not (root / ".git").exists():
        section.score = 80
        section.add("info", "This directory is not a Git repository.", "Initialize Git before sharing or releasing the project.")
        return section
    if not (root / ".gitignore").exists():
        section.score -= 20
        section.add("warning", "No .gitignore found.", "Ignore virtual environments, caches, and build output.")
    try:
        result = subprocess.run(["git", "status", "--porcelain"], cwd=root, text=True, capture_output=True, timeout=3, check=False)
        changes = result.stdout.splitlines()
        if changes:
            section.score -= min(20, len(changes))
            section.add("info", f"{len(changes)} uncommitted Git change(s).", "Commit or stash work when you reach a clean checkpoint.")
    except (OSError, subprocess.TimeoutExpired):
        section.add("info", "Git status could not be checked.")
    return section


def analyze(path: str | Path = ".") -> Report:
    """Analyze a project directory and return a report. Never changes the project."""
    root = Path(path).expanduser().resolve()
    if not root.is_dir():
        raise ValueError(f"Not a directory: {root}")
    files = _python_files(root)
    config = _read_toml(root / "pyproject.toml")
    source = _source_files(root, files)
    sections = [
        _packaging(root, config),
        _dependencies(root, config, source),
        _compatibility(config, source),
        _structure(root, files),
        _testing(root, files),
        _security(root, files),
        _documentation(root),
        _git_health(root),
    ]
    return Report(path=root, sections=sections, files_scanned=len(files))
