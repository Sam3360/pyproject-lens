import io
import tempfile
import unittest
from contextlib import redirect_stderr
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
        with redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit) as err:
                main([".", "--json", "-", "--markdown", "-"])
        self.assertEqual(err.exception.code, 2)

    def test_html_report_is_escaped(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            rep = analyze(root)
            rep.sections[0].add("warning", "<check this>")
            out = root / "report.html"
            text = rep.to_html(out)
            saved = out.read_text(encoding="utf-8")
        self.assertIn("<!doctype html>", text)
        self.assertIn("&lt;check this&gt;", text)
        self.assertEqual(text, saved)

    def test_dependency_alias_does_not_warn(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "pyproject.toml").write_text('[project]\nname = "demo"\ndependencies = ["PyYAML"]\n')
            (root / "app.py").write_text("import yaml\n")
            rep = analyze(root)
        deps = next(sec for sec in rep.sections if sec.name == "Dependencies")
        self.assertEqual(deps.findings, [])

    def test_missing_dependency_has_import_location(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "src").mkdir()
            (root / "src" / "app.py").write_text("\n\nimport requestz\n")
            rep = analyze(root)
        deps = next(sec for sec in rep.sections if sec.name == "Dependencies")
        self.assertEqual(deps.findings[0].path, "src/app.py:3")

    def test_broken_toml_gives_one_packaging_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "pyproject.toml").write_text("[project\n")
            rep = analyze(root)
        pack = next(sec for sec in rep.sections if sec.name == "Packaging")
        self.assertEqual(pack.score, 45)
        self.assertEqual(len(pack.findings), 1)

    def test_ci_ignores_text_score_in_config(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "pyproject.toml").write_text('[tool.pyproject-lens]\nminimum_score = "eighty"\n')
            code = main([str(root), "--ci"])
        self.assertEqual(code, 0)

    def test_env_needs_an_ignore_rule(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".env").write_text("TOKEN=not-real\n")
            (root / ".gitignore").write_text("__pycache__/\n")
            rep = analyze(root)
        sec = next(sec for sec in rep.sections if sec.name == "Security")
        self.assertIn("not clearly ignored", sec.findings[0].message)

    def test_ignored_env_does_not_warn(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".env").write_text("TOKEN=not-real\n")
            (root / ".gitignore").write_text(".env\n")
            rep = analyze(root)
        sec = next(sec for sec in rep.sections if sec.name == "Security")
        self.assertEqual(sec.findings, [])
