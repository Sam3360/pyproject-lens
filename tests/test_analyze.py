import tempfile
import unittest
from pathlib import Path

from pyproject_lens import analyze
from pyproject_lens.cli import main


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
        self.assertEqual([section.name for section in report.sections], ["Packaging", "Dependencies", "Python compatibility", "Project structure", "Testing", "Security", "Documentation", "Repository hygiene"])

    def test_json_is_valid(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            report = analyze(temporary)
        self.assertIn('"score"', report.to_json())

    def test_security_reports_hard_coded_secret(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "app.py").write_text('API_KEY = "not-a-real-key"\n')
            report = analyze(root)
        security = next(section for section in report.sections if section.name == "Security")
        self.assertEqual(security.score, 70)
        self.assertIn("hard-coded secret", security.findings[0].message)

    def test_testing_does_not_claim_coverage(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "app.py").write_text("def run(): pass\n")
            report = analyze(root)
        testing = next(section for section in report.sections if section.name == "Testing")
        self.assertEqual(testing.score, 55)
        self.assertIn("No test files", testing.findings[0].message)

    def test_markdown_has_plain_separators(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            text = analyze(tmp).to_markdown()
        self.assertIn(" - ", text)
        self.assertNotIn("â", text)

    def test_cli_allows_one_output_type(self) -> None:
        with self.assertRaises(SystemExit) as err:
            main([".", "--json", "-", "--markdown", "-"])
        self.assertEqual(err.exception.code, 2)
