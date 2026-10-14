"""Safe, deterministic fixes for common project issues.

Every fix follows the same contract:

- only fills gaps; never overwrites or rewrites an existing, meaningful value
- never touches fields handled by dynamic versioning (``dynamic = [...]``)
- refuses to guess where guessing could break a build (e.g. no ``readme`` key
  is added unless a README file actually exists)
- prints one line per action to stderr: ``FIXED:``, ``SKIPPED:``, or nothing
  when there was nothing to do
"""

from __future__ import annotations

from pathlib import Path
import re
import sys

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - Python 3.9/3.10
    import tomli as tomllib  # type: ignore[no-redef]

from .analyzers import _env_ignored

# Values that signal dynamic versioning tooling wrote the field; never replace them.
_PLACEHOLDER_VERSIONS = {"0.0.0", "0.0.0.post0"}

_DEFAULT_GITIGNORE = """__pycache__/
*.py[cod]
*.egg-info/
.venv/
venv/
build/
dist/
.pytest_cache/
.mypy_cache/
.ruff_cache/
.coverage
"""


def _note(message: str) -> None:
    print(message, file=sys.stderr)


def _read_text(path: Path) -> str:
    """Read text preserving exact line endings (no universal-newline translation)."""
    with path.open("r", encoding="utf-8", errors="replace", newline="") as handle:
        return handle.read()


def _write_text(path: Path, text: str) -> None:
    """Write text exactly as given, without newline translation."""
    with path.open("w", encoding="utf-8", newline="") as handle:
        handle.write(text)


def _load_project(path: Path) -> dict | None:
    """Return the parsed [project] table, or None when it cannot be read."""
    try:
        with path.open("rb") as handle:
            config = tomllib.load(handle)
    except (OSError, tomllib.TOMLDecodeError):
        return None
    project = config.get("project")
    return project if isinstance(project, dict) else {}


def _valid_name(text: str) -> str:
    return re.sub(r"[^a-zA-Z0-9._-]+", "-", text).strip("-") or "my-project"


def _insert_key(text: str, key: str, value: str) -> str:
    """Insert ``key = value`` at the top of the [project] table.

    Appends a new ``[project]`` table when there is none. Existing lines are
    never reordered, reindented, or rewritten, and the file's own line-ending
    style is reused for the inserted line.
    """
    newline = "\r\n" if "\r\n" in text else "\n"
    match = re.search(r"^\[project\][^\[]*", text, re.MULTILINE)
    if match:
        block = match.group(0)
        # Insert without a trailing newline: the header line's own newline
        # terminates the inserted line, so no blank line is introduced.
        line = f"{key} = {value}"
        updated = block.replace("[project]", f"[project]{newline}{line}", 1)
        return text[: match.start()] + updated + text[match.end() :]
    if text and not text.endswith(("\n", "\r\n")):
        text += newline
    separator = newline if text else ""
    return text + separator + f"[project]{newline}{key} = {value}{newline}"


def _fix_missing_fields(root: Path) -> None:
    """Add missing standard [project] fields with sensible defaults."""
    pyproject = root / "pyproject.toml"
    if not pyproject.is_file():
        return
    project = _load_project(pyproject)
    if project is None:
        _note("SKIPPED: pyproject.toml could not be parsed, so no fields were added")
        return
    dynamic = project.get("dynamic", [])
    dynamic = set(dynamic) if isinstance(dynamic, list) else set()
    try:
        text = _read_text(pyproject)
    except OSError:
        return
    original = text

    if "name" not in project and "name" not in dynamic:
        text = _insert_key(text, "name", repr(_valid_name(root.resolve().name)))
        _note(f"FIXED: added project.name = {_valid_name(root.resolve().name)!r}")
    if "version" not in project and "version" not in dynamic:
        text = _insert_key(text, "version", repr("0.1.0"))
        _note("FIXED: added project.version = '0.1.0'")
    if "requires-python" not in project and "requires-python" not in dynamic:
        text = _insert_key(text, "requires-python", repr(">=3.9"))
        _note("FIXED: added project.requires-python = '>=3.9'")
    if "readme" not in project and "readme" not in dynamic:
        for candidate in ("README.md", "README.rst", "README.txt"):
            if (root / candidate).is_file():
                text = _insert_key(text, "readme", repr(candidate))
                _note(f"FIXED: added project.readme = {candidate!r}")
                break

    if text != original:
        _write_text(pyproject, text)


def _fix_env_gitignore(root: Path) -> None:
    """Add a .env rule to .gitignore when a .env file is not ignored."""
    env = root / ".env"
    ignore = root / ".gitignore"
    if not env.is_file() or _env_ignored(root):
        return
    if ignore.exists() and not ignore.is_file():
        _note("SKIPPED: .gitignore is not a file")
        return
    old = _read_text(ignore) if ignore.is_file() else ""
    end = "" if not old or old.endswith("\n") else "\n"
    _write_text(ignore, f"{old}{end}.env\n")
    _note("FIXED: added .env to .gitignore")


def _fix_starter_gitignore(root: Path) -> None:
    """Create a starter .gitignore for Git repositories that have none."""
    ignore = root / ".gitignore"
    if ignore.exists():
        return  # exists (file or not): the .env rule above already handled files
    if not (root / ".git").is_dir():
        return  # .gitignore only matters inside a Git repository
    _write_text(ignore, _DEFAULT_GITIGNORE)
    _note("FIXED: created a starter .gitignore")


def apply_safe_fixes(path: str | Path) -> None:
    """Apply every safe fix to the project at ``path``. Idempotent by design."""
    root = Path(path).expanduser()
    _fix_missing_fields(root)
    _fix_env_gitignore(root)
    _fix_starter_gitignore(root)
