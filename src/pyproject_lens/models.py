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
