"""Command line interface for pyproject-lens."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

from .analyzers import analyze


def _print_report(report: object) -> None:
    from .models import Report
    report = report  # keep the terminal-friendly type narrow below
    assert isinstance(report, Report)
    print("pyproject-lens — Project Health Report")
    print(f"Project: {report.path.name}  |  Python files scanned: {report.files_scanned}")
    print("=" * 58)
    for section in report.sections:
        print(f"\n{section.name.upper()}  {section.score}/100")
        if not section.findings:
            print("  OK — nothing obvious found")
        for finding in section.findings:
            print(f"  {finding.level.upper()}: {finding.message}")
            if finding.recommendation:
                print(f"    Try: {finding.recommendation}")
    warnings = sum(item.level in {"warning", "error"} for item in report.findings)
    print(f"\nPROJECT HEALTH: {report.score}/100  |  {warnings} warning(s)")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="A small health scanner for Python projects.")
    parser.add_argument("path", nargs="?", default=".", help="project directory (default: current directory)")
    parser.add_argument("--json", metavar="FILE", help="write a JSON report to FILE; use - for stdout")
    parser.add_argument("--markdown", metavar="FILE", help="write a Markdown report to FILE; use - for stdout")
    parser.add_argument("--ci", action="store_true", help="return an error if minimum_score is not met")
    parser.add_argument("--minimum-score", type=int, help="score needed for --ci (overrides pyproject.toml)")
    args = parser.parse_args(argv)
    try:
        report = analyze(args.path)
    except ValueError as error:
        parser.error(str(error))
    if args.json:
        text = report.to_json(None if args.json == "-" else args.json)
        if args.json == "-":
            print(text, end="")
    elif args.markdown:
        text = report.to_markdown(None if args.markdown == "-" else args.markdown)
        if args.markdown == "-":
            print(text, end="")
    else:
        _print_report(report)
    if args.ci:
        threshold = args.minimum_score
        if threshold is None:
            import tomllib
            try:
                with (Path(args.path) / "pyproject.toml").open("rb") as handle:
                    threshold = tomllib.load(handle).get("tool", {}).get("pyproject-lens", {}).get("minimum_score", 0)
            except (OSError, tomllib.TOMLDecodeError):
                threshold = 0
        if report.score < threshold:
            print(f"CI FAILED: score {report.score} is below minimum_score {threshold}", file=sys.stderr)
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
