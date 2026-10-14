"""The project checks: dependency-free, architecture-aware, and hard-capped for safety.

Every directory walk is bounded by MAX_FILES and MAX_SCAN_DEPTH, symlinked
directories are never followed, and the limits are configurable per project
(``[tool.pyproject-lens]``) or per run (``--max-files`` / ``--max-depth`` /
``--exclude``), so pointing the scanner at a huge non-project tree fails fast
with a clear error instead of hanging the shell.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass, field
from fnmatch import fnmatch
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Sequence

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - Python 3.9/3.10
    import tomli as tomllib  # type: ignore[no-redef]

from .models import Report, Section

STDLIB = set(getattr(sys, "stdlib_module_names", ()))
IMPORT_NAMES = {
    "PIL": "pillow",
    "bs4": "beautifulsoup4",
    "cv2": "opencv-python",
    "dateutil": "python-dateutil",
    "dotenv": "python-dotenv",
    "git": "gitpython",
    "jwt": "pyjwt",
    "sklearn": "scikit-learn",
    "yaml": "pyyaml",
}

# --- Safety limits ---------------------------------------------------------
# Hard caps so the scanner can never wander through a whole system directory.
MAX_FILES = 5000
MAX_SCAN_DEPTH = 12

DEFAULT_SKIP_DIRS = frozenset(
    {
        ".git",
        ".hg",
        ".svn",
        ".venv",
        "venv",
        "env",
        "__pycache__",
        "build",
        "dist",
        ".tox",
        ".nox",
        ".eggs",
        "*.egg-info",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        ".hypothesis",
        "node_modules",
        ".github",
        ".idea",
        ".vscode",
    }
)


class ScanningLimitExceeded(RuntimeError):
    """Raised when a directory tree is too large to scan safely."""


@dataclass
class ScanOptions:
    """Limits and exclusions for one scan."""

    max_files: int = MAX_FILES
    max_depth: int = MAX_SCAN_DEPTH
    exclude: tuple[str, ...] = ()
    skip_dirs: frozenset[str] = DEFAULT_SKIP_DIRS


def _skip_dir(name: str, patterns: frozenset[str]) -> bool:
    """True when a directory name matches a skip entry (exact or glob)."""
    return any(fnmatch(name, pattern) for pattern in patterns)


def _is_excluded(path: Path, root: Path, patterns: tuple[str, ...]) -> bool:
    """True when a relative path (or its basename) matches an exclude glob."""
    if not patterns:
        return False
    try:
        relative = path.relative_to(root).as_posix()
    except ValueError:
        return False
    return any(fnmatch(relative, pattern) or fnmatch(path.name, pattern) for pattern in patterns)


def _iter_py_files(root: Path, options: ScanOptions) -> Sequence[Path]:
    """Yield .py files under root without following symlinks, bounded by depth."""

    def walk(directory: Path, depth: int) -> Sequence[Path]:
        if depth > options.max_depth:
            return []
        try:
            entries = list(os.scandir(directory))
        except OSError:
            return []
        found: list[Path] = []
        for entry in entries:
            try:
                is_file = entry.is_file(follow_symlinks=False)
                is_dir = entry.is_dir(follow_symlinks=False)
            except OSError:
                continue
            if is_file and entry.name.endswith(".py"):
                found.append(Path(entry.path))
            elif is_dir and not _skip_dir(entry.name, options.skip_dirs) and not _is_excluded(Path(entry.path), root, options.exclude):
                found.extend(walk(Path(entry.path), depth + 1))
        return found

    return walk(root, 1)


def _python_files(root: Path, options: ScanOptions) -> list[Path]:
    """Collect Python files under hard caps; raise instead of scanning forever."""
    found: list[Path] = []
    for path in _iter_py_files(root, options):
        if _is_excluded(path, root, options.exclude):
            continue
        found.append(path)
        if len(found) > options.max_files:
            raise ScanningLimitExceeded(
                f"Found more than {options.max_files} Python files under {root} "
                f"(max_files={options.max_files}, depth limit {options.max_depth}). "
                "This does not look like a normal project tree. Raise the cap with "
                "--max-files / --max-depth, or add --exclude patterns (also "
                "configurable under [tool.pyproject-lens])."
            )
    return sorted(found)


def _positive_int(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) and value > 0 else None


def _collect_options(
    root: Path,
    config: dict[str, Any],
    max_files: int | None,
    max_depth: int | None,
    exclude: Sequence[str] | None,
) -> ScanOptions:
    """Merge limits: module defaults < [tool.pyproject-lens] < explicit arguments."""
    tool = config.get("tool", {})
    lens = tool.get("pyproject-lens", {}) if isinstance(tool, dict) else {}
    lens = lens if isinstance(lens, dict) else {}
    files = max_files if max_files is not None else _positive_int(lens.get("max_files"))
    depth = max_depth if max_depth is not None else _positive_int(lens.get("max_depth"))
    if exclude is not None:
        patterns = tuple(str(item) for item in exclude)
    else:
        configured = lens.get("exclude", [])
        patterns = tuple(str(item) for item in configured) if isinstance(configured, list) else ()
    return ScanOptions(
        max_files=files if files else MAX_FILES,
        max_depth=depth if depth else MAX_SCAN_DEPTH,
        exclude=patterns,
    )


# --- Small helpers ---------------------------------------------------------


def _source_files(root: Path, files: list[Path]) -> list[Path]:
    """Return project code, leaving test-only imports out of dependency checks."""
    return [path for path in files if not _is_test_file(path, root)]


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


# --- Smarter rule inputs ----------------------------------------------------


def _requirements_txt_names(root: Path) -> set[str]:
    """Distribution names declared in requirements*.txt (comments and flags removed)."""
    names: set[str] = set()
    for path in sorted(root.glob("requirements*.txt")):
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for line in text.splitlines():
            line = line.split("#", 1)[0].strip()
            if not line or line.startswith(("-", ".")):
                continue
            if "@" in line:  # direct URL reference: keep the package name only
                line = line.split("@", 1)[0].strip()
            names.add(_distribution_name(line))
    return names


_LOWER_BOUND = re.compile(r"(?:>=|==|~=)\s*(\d+)\.(\d+)")


def _min_python(requires: str) -> tuple[int, int] | None:
    """Extract a lower-bound (major, minor) from a requires-python specifier."""
    versions = [(int(major), int(minor)) for major, minor in _LOWER_BOUND.findall(requires)]
    return max(versions) if versions else None


def _is_test_file(path: Path, root: Path | None = None) -> bool:
    name = path.name
    if name.startswith("test_") or name.endswith("_test.py") or name in {"tests.py", "conftest.py"}:
        return True
    if root is not None:
        try:
            parts = path.relative_to(root).parts
        except ValueError:
            return False
        return any(part in {"tests", "test"} for part in parts[:-1])
    return False


def _ci_test_config(root: Path) -> bool:
    """Evidence that test tooling is configured even if no test file was found."""
    config = _read_toml(root / "pyproject.toml")
    tools = config.get("tool", {})
    if isinstance(tools, dict) and "pytest" in tools:
        return True
    return (root / "tox.ini").exists() or (root / "noxfile.py").exists()


# --- Section analyzers ------------------------------------------------------


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
    missing = sorted(
        name
        for name in imports
        if name not in STDLIB and name not in local and IMPORT_NAMES.get(name, name.replace("_", "-")).lower() not in declared
    )
    if missing:
        # requirements.txt counts as an honest declaration, but say so: it is
        # not visible to installers the way project.dependencies is.
        req_names = _requirements_txt_names(root)
        if req_names:
            covered = [name for name in missing if IMPORT_NAMES.get(name, name.replace("_", "-")).lower() in req_names]
            missing = [name for name in missing if name not in covered]
            if covered:
                section.score -= min(10, 5 * len(covered))
                section.add(
                    "info",
                    f"{len(covered)} import(s) are only declared in requirements.txt.",
                    "Mirror runtime dependencies in project.dependencies so installers can see them.",
                )
    if missing:
        section.score -= min(45, 10 * len(missing))
        for name in missing[:8]:
            section.add("warning", f"'{name}' is imported but not declared.", "Add it to project.dependencies if it is a runtime dependency.", imports[name])
    if (root / "requirements.txt").exists() and not declared:
        section.score -= 10
        section.add("info", "requirements.txt exists but project.dependencies is empty.", "Consider keeping runtime dependencies in pyproject.toml.")
    section.score = max(0, section.score)
    return section


# Syntax features gated on the declared minimum Python version.
_FEATURE_GATES: tuple[tuple[tuple[int, int], str, str], ...] = (
    ((3, 10), "match/case", "match/case statements"),
    ((3, 12), "type statements", "the 'type' alias statement"),
)


def _feature_present(node: ast.AST, feature: str) -> bool:
    if feature == "match/case":
        match_cls = getattr(ast, "Match", None)
        return bool(match_cls) and isinstance(node, match_cls)
    if feature == "type statements":
        alias_cls = getattr(ast, "TypeAlias", ())
        return bool(alias_cls) and isinstance(node, alias_cls)
    return False


def _compatibility(root: Path, config: dict[str, Any], files: list[Path]) -> Section:
    section = Section("Python compatibility")
    requires = _project(config).get("requires-python", "")
    requires = requires if isinstance(requires, str) else ""
    if not requires:
        section.score = 80
        section.add("info", "Compatibility cannot be checked without requires-python.", "Declare supported Python versions in pyproject.toml.")
        return section
    floor = _min_python(requires)
    if floor is None:
        section.score = 85
        section.add(
            "info",
            f"requires-python ('{requires}') has no clear lower bound, so deep compatibility checks were skipped.",
            "Use a lower bound such as '>=3.10'.",
        )
        return section
    for gate, label, description in _FEATURE_GATES:
        if floor >= gate:
            continue
        for file in files:
            try:
                tree = ast.parse(file.read_text(encoding="utf-8"), filename=str(file))
            except (OSError, UnicodeDecodeError, SyntaxError):
                continue
            if any(_feature_present(node, label) for node in ast.walk(tree)):
                section.score = 60
                section.add(
                    "warning",
                    f"{description} need Python {gate[0]}.{gate[1]}+ but requires-python is '{requires}'.",
                    f"Raise requires-python to >={gate[0]}.{gate[1]} or avoid the syntax.",
                    file.relative_to(root).as_posix(),
                )
                break
    return section


def _structure(root: Path, files: list[Path], options: ScanOptions) -> Section:
    section = Section("Project structure")
    source_root = root / "src"
    scan_root = source_root if source_root.is_dir() else root
    try:
        entries = list(scan_root.iterdir())
    except OSError:
        entries = []
    packages = [path for path in entries if path.is_dir() and (path / "__init__.py").exists()]
    if source_root.is_dir() and not packages:
        section.score -= 25
        section.add("warning", "src/ exists but no package was detected.", "Put your package in src/ with an __init__.py file.", "src")
    # Root crowding: scripts and tooling entry points are expected at the root
    # of a project (Flask/Django apps, manage.py, cli.py, setup tooling), so
    # only application modules count toward the "crowded" signal.
    top_level = [path for path in files if path.parent == root and path.name not in {"setup.py", "conftest.py"}]
    entry_point_names = {"main.py", "run.py", "cli.py", "app.py", "wsgi.py", "asgi.py", "manage.py", "server.py", "__main__.py"}
    tooling = [path for path in top_level if path.name.startswith(("setup", "conf", "manage")) or path.name in {"noxfile.py", "tasks.py"}]
    scripts = [path for path in top_level if path.name in entry_point_names]
    application = [path for path in top_level if path not in tooling and path not in scripts]
    threshold = 10 if scripts or tooling else 6
    if len(application) > threshold:
        section.score -= 15
        section.add("info", f"{len(application)} application Python files live at the project root.", "Consider grouping application code into a package.")
    if not packages and not (root / "src").is_dir() and len(files) > 3:
        section.score -= 10
        section.add("info", "No importable package was detected.", "Wrapping modules in a package makes imports and installs predictable.")
    return section


def _testing(root: Path, files: list[Path]) -> Section:
    section = Section("Testing")
    test_files = [path for path in files if _is_test_file(path, root)]
    source_files = [path for path in _source_files(root, files) if path.name != "__init__.py"]
    if not test_files:
        if _ci_test_config(root) or (root / ".github").is_dir():
            section.score = 85
            section.add("info", "No test files were found, but test tooling appears to be configured.", "Add a few test_*.py files for the code users rely on.")
        else:
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


def _env_ignored(root: Path) -> bool:
    ignore = root / ".gitignore"
    if not ignore.is_file():
        return False
    pats = [line.strip().lstrip("/") for line in ignore.read_text(encoding="utf-8", errors="replace").splitlines() if line.strip() and not line.startswith("#")]
    return any(fnmatch(".env", pat) for pat in pats)


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
    if env.is_file() and not _env_ignored(root):
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


def analyze(
    path: str | Path = ".",
    *,
    max_files: int | None = None,
    max_depth: int | None = None,
    exclude: Sequence[str] | None = None,
) -> Report:
    """Analyze a project directory and return a report. Never changes the project.

    Limits default to the module caps, then ``[tool.pyproject-lens]`` in the
    project's pyproject.toml, then these keyword arguments (highest priority).
    Raises :class:`ScanningLimitExceeded` when the tree is too large to scan
    safely.
    """
    root = Path(path).expanduser().resolve()
    if not root.is_dir():
        raise ValueError(f"Not a directory: {root}")
    config = _read_toml(root / "pyproject.toml")
    options = _collect_options(root, config, max_files, max_depth, exclude)
    files = _python_files(root, options)
    source = _source_files(root, files)
    sections = [
        _packaging(root, config),
        _dependencies(root, config, source),
        _compatibility(root, config, source),
        _structure(root, files, options),
        _testing(root, files),
        _security(root, source),
        _documentation(root),
        _git_health(root),
    ]
    return Report(path=root, sections=sections, files_scanned=len(files))
