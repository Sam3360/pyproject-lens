"""The intentionally small, dependency-free project checks."""

from __future__ import annotations

import ast
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


def _python_files(root: Path) -> list[Path]:
    return [path for path in root.rglob("*.py") if not any(part in SKIP_DIRS for part in path.parts)]


def _read_toml(path: Path) -> dict[str, Any]:
    try:
        with path.open("rb") as handle:
            return tomllib.load(handle)
    except (OSError, tomllib.TOMLDecodeError):
        return {}


def _top_level_imports(files: list[Path]) -> set[str]:
    imports: set[str] = set()
    for file in files:
        try:
            tree = ast.parse(file.read_text(encoding="utf-8"), filename=str(file))
        except (OSError, UnicodeDecodeError, SyntaxError):
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports.update(name.name.split(".")[0] for name in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
                imports.add(node.module.split(".")[0])
    return imports


def _distribution_name(value: str) -> str:
    return re.split(r"[<>=!~;[ ]", value, maxsplit=1)[0].lower().replace("_", "-")


def _packaging(root: Path, config: dict[str, Any]) -> Section:
    section = Section("Packaging")
    pyproject = root / "pyproject.toml"
    project = config.get("project", {})
    if not pyproject.exists():
        section.score = 30
        section.add("warning", "No pyproject.toml found.", "Add one to describe how your project is built.")
        return section
    if not config:
        section.score = 45
        section.add("error", "pyproject.toml could not be read.", "Check its TOML syntax.", "pyproject.toml")
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
    declared = {_distribution_name(item) for item in config.get("project", {}).get("dependencies", [])}
    imports = _top_level_imports(files)
    local = {path.stem for path in files}
    for file in files:
        try:
            relative = file.relative_to(root)
        except ValueError:
            continue
        local.update(part for part in relative.parts[:-1] if part not in {"src", "tests"})
    missing = sorted(name for name in imports if name not in STDLIB and name not in local and name.replace("_", "-") not in declared)
    if missing:
        section.score -= min(45, 10 * len(missing))
        for name in missing[:8]:
            section.add("warning", f"'{name}' is imported but not declared.", "Add it to project.dependencies if it is a runtime dependency.")
    if (root / "requirements.txt").exists() and not declared:
        section.score -= 10
        section.add("info", "requirements.txt exists but project.dependencies is empty.", "Consider keeping runtime dependencies in pyproject.toml.")
    return section


def _compatibility(config: dict[str, Any], files: list[Path]) -> Section:
    section = Section("Python compatibility")
    requires = config.get("project", {}).get("requires-python", "")
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
    sections = [_packaging(root, config), _dependencies(root, config, files), _compatibility(config, files), _structure(root, files), _git_health(root)]
    return Report(path=root, sections=sections, files_scanned=len(files))
