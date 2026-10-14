"""Command line interface for pyproject-lens."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

from . import __version__
from .analyzers import MAX_FILES, MAX_SCAN_DEPTH, ScanningLimitExceeded, _read_toml, analyze
from .fixes import apply_safe_fixes
from .models import Report


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="pyproject-lens",
        description="A small health scanner for Python projects.",
    )
    p.add_argument("path", nargs="?", default=".", help="project directory (default: current directory)")
    p.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    out = p.add_mutually_exclusive_group()
    out.add_argument("--json", metavar="FILE", help="write a JSON report to FILE; use - for stdout")
    out.add_argument("--markdown", metavar="FILE", help="write a Markdown report to FILE; use - for stdout")
    out.add_argument("--html", metavar="FILE", help="write a standalone HTML report to FILE")
    p.add_argument("--fix", action="store_true", help="apply safe fixes (missing pyproject fields, .env ignore rule, starter .gitignore)")
    p.add_argument("--ci", action="store_true", help="return an error if minimum_score is not met")
    p.add_argument("--minimum-score", type=int, help="score needed for --ci (overrides pyproject.toml)")
    p.add_argument(
        "--max-files",
        type=int,
        default=None,
        metavar="N",
        help=f"stop with an error above N Python files (default: {MAX_FILES})",
    )
    p.add_argument(
        "--max-depth",
        type=int,
        default=None,
        metavar="N",
        help=f"do not descend deeper than N directory levels (default: {MAX_SCAN_DEPTH})",
    )
    p.add_argument(
        "--exclude",
        action="append",
        default=None,
        metavar="PATTERN",
        help="skip paths matching a glob pattern (repeatable, also settable in pyproject.toml)",
    )
    return p


def _show(rep: Report) -> None:
    print("pyproject-lens - Project Health Report")
    print(f"Project: {rep.path.name}  |  Python files scanned: {rep.files_scanned}")
    print("=" * 58)
    for sec in rep.sections:
        print(f"\n{sec.name.upper()}  {sec.score}/100")
        if not sec.findings:
            print("  OK - nothing obvious found")
        for item in sec.findings:
            print(f"  {item.level.upper()}: {item.message}")
            if item.recommendation:
                print(f"    Try: {item.recommendation}")
    warns = sum(item.level in {"warning", "error"} for item in rep.findings)
    print(f"\nPROJECT HEALTH: {rep.score}/100  |  {warns} warning(s)")


def main(args: list[str] | None = None) -> int:
    p = _build_parser()
    ns = p.parse_args(args)
    if ns.max_files is not None and ns.max_files < 1:
        p.error("--max-files must be at least 1")
    if ns.max_depth is not None and ns.max_depth < 1:
        p.error("--max-depth must be at least 1")
    if ns.fix:
        apply_safe_fixes(ns.path)
    try:
        rep = analyze(ns.path, max_files=ns.max_files, max_depth=ns.max_depth, exclude=ns.exclude)
    except ValueError as err:
        p.error(str(err))
    except ScanningLimitExceeded as err:
        print(f"SCAN ABORTED: {err}", file=sys.stderr)
        return 2
    if ns.json:
        text = rep.to_json(None if ns.json == "-" else ns.json)
        if ns.json == "-":
            print(text, end="")
    elif ns.markdown:
        text = rep.to_markdown(None if ns.markdown == "-" else ns.markdown)
        if ns.markdown == "-":
            print(text, end="")
    elif ns.html:
        rep.to_html(ns.html)
        print(f"HTML report written to {ns.html}")
    else:
        _show(rep)
    if ns.ci:
        score = ns.minimum_score
        if score is None:
            try:
                data = _read_toml(Path(ns.path) / "pyproject.toml")
                score = data.get("tool", {}).get("pyproject-lens", {}).get("minimum_score", 0)
                score = score if isinstance(score, int) else 0
            except (AttributeError, OSError):
                score = 0
        if rep.score < score:
            print(f"CI FAILED: score {rep.score} is below minimum_score {score}", file=sys.stderr)
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
