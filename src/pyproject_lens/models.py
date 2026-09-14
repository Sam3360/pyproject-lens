"""Small data objects used by the scanner."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from html import escape
from pathlib import Path
from typing import Any
import json


@dataclass
class Finding:
    level: str
    message: str
    recommendation: str | None = None
    path: str | None = None


@dataclass
class Section:
    name: str
    score: int = 100
    findings: list[Finding] = field(default_factory=list)

    def add(self, level: str, message: str, recommendation: str | None = None, path: str | None = None) -> None:
        self.findings.append(Finding(level, message, recommendation, path))


@dataclass
class Report:
    path: Path
    sections: list[Section]
    files_scanned: int

    @property
    def score(self) -> int:
        if not self.sections:
            return 100
        return round(sum(sec.score for sec in self.sections) / len(self.sections))

    @property
    def findings(self) -> list[Finding]:
        return [item for sec in self.sections for item in sec.findings]

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": str(self.path),
            "score": self.score,
            "files_scanned": self.files_scanned,
            "sections": [asdict(sec) for sec in self.sections],
        }

    def to_json(self, out: str | Path | None = None) -> str:
        text = json.dumps(self.to_dict(), indent=2) + "\n"
        if out:
            Path(out).write_text(text, encoding="utf-8")
        return text

    def to_markdown(self, out: str | Path | None = None) -> str:
        lines = ["# pyproject-lens report", "", f"**Project:** `{self.path.name}`", f"**Health:** {self.score}/100", ""]
        for sec in self.sections:
            lines.extend([f"## {sec.name} - {sec.score}/100", ""])
            if not sec.findings:
                lines.extend(["No issues detected.", ""])
                continue
            for item in sec.findings:
                tip = f" - {item.recommendation}" if item.recommendation else ""
                loc = f" (`{item.path}`)" if item.path else ""
                lines.append(f"- **{item.level.upper()}**{loc}: {item.message}{tip}")
            lines.append("")
        text = "\n".join(lines)
        if out:
            Path(out).write_text(text, encoding="utf-8")
        return text

    def to_html(self, out: str | Path | None = None) -> str:
        cards = []
        for sec in self.sections:
            rows = []
            for item in sec.findings:
                loc = f"<code>{escape(item.path)}</code> " if item.path else ""
                tip = f"<p>Try: {escape(item.recommendation)}</p>" if item.recommendation else ""
                rows.append(f"<li class=\"{escape(item.level)}\">{loc}<b>{escape(item.level.upper())}</b>: {escape(item.message)}{tip}</li>")
            body = "<p class=\"ok\">No issues detected.</p>" if not rows else f"<ul>{''.join(rows)}</ul>"
            cards.append(f"<section><header><h2>{escape(sec.name)}</h2><b>{sec.score}/100</b></header>{body}</section>")
        text = f"""<!doctype html>
<html lang=\"en\"><head><meta charset=\"utf-8\"><meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">
<title>pyproject-lens - {escape(self.path.name)}</title>
<style>
body {{ max-width: 900px; margin: auto; padding: 28px 18px; background: #f6f7fb; color: #1f2937; font: 16px/1.5 Arial, sans-serif; }}
h1 {{ margin-bottom: 0; }} .sub {{ color: #52606d; }} .score {{ color: #2563eb; font-size: 44px; font-weight: bold; }}
section {{ margin: 16px 0; padding: 16px 20px; background: white; border: 1px solid #dfe3ea; border-radius: 8px; }}
header {{ display: flex; justify-content: space-between; }} h2 {{ margin: 0; font-size: 19px; }} li {{ margin: 10px 0; }}
.warning {{ color: #92400e; }} .error {{ color: #b91c1c; }} .ok {{ color: #166534; }} li p {{ color: #4b5563; margin: 3px 0; }} code {{ background: #eef2ff; padding: 2px 4px; }}
</style></head><body>
<h1>pyproject-lens</h1><p class=\"sub\">Project health report for <b>{escape(self.path.name)}</b> - {self.files_scanned} Python file(s) scanned</p>
<div class=\"score\">{self.score}/100</div>{''.join(cards)}
</body></html>\n"""
        if out:
            Path(out).write_text(text, encoding="utf-8")
        return text
