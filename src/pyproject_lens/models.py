"""Small data objects used by the scanner."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
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
        return round(sum(section.score for section in self.sections) / len(self.sections))

    @property
    def findings(self) -> list[Finding]:
        return [finding for section in self.sections for finding in section.findings]

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": str(self.path),
            "score": self.score,
            "files_scanned": self.files_scanned,
            "sections": [asdict(section) for section in self.sections],
        }

    def to_json(self, output: str | Path | None = None) -> str:
        text = json.dumps(self.to_dict(), indent=2) + "\n"
        if output:
            Path(output).write_text(text, encoding="utf-8")
        return text

    def to_markdown(self, output: str | Path | None = None) -> str:
        lines = [f"# pyproject-lens report", "", f"**Project:** `{self.path.name}`", f"**Health:** {self.score}/100", ""]
        for section in self.sections:
            lines.extend([f"## {section.name} — {section.score}/100", ""])
            if not section.findings:
                lines.extend(["No issues detected.", ""])
                continue
            for finding in section.findings:
                detail = f" — {finding.recommendation}" if finding.recommendation else ""
                location = f" (`{finding.path}`)" if finding.path else ""
                lines.append(f"- **{finding.level.upper()}**{location}: {finding.message}{detail}")
            lines.append("")
        text = "\n".join(lines)
        if output:
            Path(output).write_text(text, encoding="utf-8")
        return text
