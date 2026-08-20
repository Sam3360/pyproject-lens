import tempfile
import unittest
from pathlib import Path

from pyproject_lens import analyze


class AnalyzeTests(unittest.TestCase):
    def test_analyze_returns_sections(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "pyproject.toml").write_text('[project]\nname = "demo"\nrequires-python = ">=3.10"\n')
            (root / "README.md").write_text("# Demo")
            (root / "src" / "demo").mkdir(parents=True)
            (root / "src" / "demo" / "__init__.py").write_text("")
            report = analyze(root)
        self.assertLessEqual(report.score, 100)
        self.assertEqual([section.name for section in report.sections], ["Packaging", "Dependencies", "Python compatibility", "Project structure", "Repository hygiene"])

    def test_json_is_valid(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            report = analyze(temporary)
        self.assertIn('"score"', report.to_json())
