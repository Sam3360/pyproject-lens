import io
import os
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

try:
    import tomllib as toml_reader
except ModuleNotFoundError:
    import tomli as toml_reader

from pyproject_lens import analyze
from pyproject_lens.analyzers import ScanningLimitExceeded
from pyproject_lens.cli import main
from pyproject_lens.fixes import apply_safe_fixes

SRC_PATH = str(Path(__file__).resolve().parents[1] / "src")


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

    def test_compatibility_works_without_match_node(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "app.py").write_text("print('hi')\n")
            with patch("pyproject_lens.analyzers.ast.Match", None, create=True):
                rep = analyze(root)
        sec = next(sec for sec in rep.sections if sec.name == "Python compatibility")
        self.assertEqual(sec.score, 80)

    def test_fix_adds_env_to_gitignore(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".env").write_text("TOKEN=not-real\n")
            with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                code = main([str(root), "--fix"])
            text = (root / ".gitignore").read_text(encoding="utf-8")
            rep = analyze(root)
        sec = next(sec for sec in rep.sections if sec.name == "Security")
        self.assertEqual(code, 0)
        self.assertEqual(text, ".env\n")
        self.assertEqual(sec.findings, [])


class SafeFixTests(unittest.TestCase):
    def _run_fix(self, root: Path) -> None:
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            apply_safe_fixes(str(root))

    def test_missing_project_fields_are_added(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "pyproject.toml").write_text("[project]\n")
            (root / "README.md").write_text("# Demo\n")
            self._run_fix(root)
            text = (root / "pyproject.toml").read_text(encoding="utf-8")
            with (root / "pyproject.toml").open("rb") as handle:
                project = toml_reader.load(handle)["project"]
        self.assertEqual(project["name"], Path(tmp).name)
        self.assertEqual(project["version"], "0.1.0")
        self.assertEqual(project["requires-python"], ">=3.9")
        self.assertEqual(project["readme"], "README.md")
        self.assertIn("[project]", text)

    def test_existing_fields_are_never_overwritten(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            original = '[project]\nname = "my-tool"\nversion = "2.3.4"\nrequires-python = ">=3.11"\n'
            (root / "pyproject.toml").write_text(original)
            self._run_fix(root)
            text = (root / "pyproject.toml").read_text(encoding="utf-8")
        self.assertEqual(text, original)

    def test_dynamic_fields_are_never_added(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "pyproject.toml").write_text('[project]\nname = "demo"\ndynamic = ["version"]\n')
            self._run_fix(root)
            with (root / "pyproject.toml").open("rb") as handle:
                project = toml_reader.load(handle)["project"]
        self.assertNotIn("version", project)

    def test_no_readme_means_no_readme_key(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "pyproject.toml").write_text("[project]\n")
            self._run_fix(root)
            with (root / "pyproject.toml").open("rb") as handle:
                project = toml_reader.load(handle)["project"]
        self.assertNotIn("readme", project)

    def test_unparseable_toml_is_skipped_untouched(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "pyproject.toml").write_text("[project\n")
            self._run_fix(root)
            text = (root / "pyproject.toml").read_text(encoding="utf-8")
        self.assertEqual(text, "[project\n")

    def test_project_table_is_created_when_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "pyproject.toml").write_text('[build-system]\nrequires = ["setuptools"]\n')
            self._run_fix(root)
            with (root / "pyproject.toml").open("rb") as handle:
                config = toml_reader.load(handle)
        self.assertEqual(config["project"]["version"], "0.1.0")
        self.assertEqual(config["build-system"]["requires"], ["setuptools"])

    def test_fixes_are_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "pyproject.toml").write_text("[project]\n")
            (root / ".env").write_text("TOKEN=not-real\n")
            (root / ".git").mkdir()
            self._run_fix(root)
            after_first = (root / "pyproject.toml").read_text(encoding="utf-8")
            ignore_after_first = (root / ".gitignore").read_text(encoding="utf-8")
            self._run_fix(root)
            after_second = (root / "pyproject.toml").read_text(encoding="utf-8")
            ignore_after_second = (root / ".gitignore").read_text(encoding="utf-8")
        self.assertEqual(after_second, after_first)
        self.assertEqual(ignore_after_second, ignore_after_first)

    def test_env_rule_still_applied_with_other_fixes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "pyproject.toml").write_text("[project]\n")
            (root / ".env").write_text("TOKEN=not-real\n")
            (root / ".gitignore").write_text("__pycache__/\n")
            self._run_fix(root)
            ignore = (root / ".gitignore").read_text(encoding="utf-8")
        self.assertTrue(ignore.startswith("__pycache__/\n"))
        self.assertIn(".env\n", ignore)

    def test_starter_gitignore_created_for_git_repos(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".git").mkdir()
            self._run_fix(root)
            ignore = (root / ".gitignore").read_text(encoding="utf-8")
        self.assertIn("__pycache__/", ignore)
        self.assertIn(".venv/", ignore)

    def test_no_starter_gitignore_outside_git_repos(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._run_fix(root)
        self.assertFalse((root / ".gitignore").exists())

    def test_existing_gitignore_is_never_replaced(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".git").mkdir()
            (root / ".gitignore").write_text("*.log\n")
            self._run_fix(root)
            ignore = (root / ".gitignore").read_text(encoding="utf-8")
        self.assertEqual(ignore, "*.log\n")

    def test_cli_fix_reports_and_rescans_clean(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "pyproject.toml").write_text("[project]\n")
            (root / ".env").write_text("TOKEN=not-real\n")
            (root / ".git").mkdir()
            err = io.StringIO()
            with redirect_stdout(io.StringIO()), redirect_stderr(err):
                code = main([str(root), "--fix", "--json", "-"])
            output = err.getvalue()
            rep = analyze(root)
        self.assertEqual(code, 0)
        self.assertIn("FIXED:", output)
        security = next(sec for sec in rep.sections if sec.name == "Security")
        self.assertEqual(security.findings, [])


class EntryPointTests(unittest.TestCase):
    def test_python_m_runs_and_reports_version(self) -> None:
        env = os.environ.copy()
        env["PYTHONPATH"] = SRC_PATH + os.pathsep + env.get("PYTHONPATH", "")
        result = subprocess.run(
            [sys.executable, "-m", "pyproject_lens", "--version"],
            capture_output=True,
            text=True,
            env=env,
            timeout=60,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("0.7.0", result.stdout)

    def test_version_flag_exits_cleanly(self) -> None:
        with redirect_stdout(io.StringIO()):
            with self.assertRaises(SystemExit) as err:
                main(["--version"])
        self.assertEqual(err.exception.code, 0)


class SafetyLimitTests(unittest.TestCase):
    def test_too_many_files_aborts_with_clear_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "a.py").write_text("x = 1\n")
            (root / "b.py").write_text("x = 2\n")
            with self.assertRaises(ScanningLimitExceeded) as err:
                analyze(root, max_files=1)
        self.assertIn("max_files", str(err.exception))
        self.assertIn("--max-files", str(err.exception))

    def test_depth_cap_ignores_deeper_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            deep = root
            for index in range(13):
                deep = deep / f"level{index}"
            deep.mkdir(parents=True)
            (deep / "app.py").write_text("x = 1\n")
            self.assertEqual(analyze(root).files_scanned, 0)
            self.assertEqual(analyze(root, max_depth=15).files_scanned, 1)

    def test_symlinked_directories_are_not_followed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            outside = root / "outside"
            outside.mkdir()
            (outside / "leak.py").write_text("x = 1\n")
            link = root / "link"
            try:
                os.symlink(outside, link, target_is_directory=True)
            except OSError:  # Windows without symlink privilege
                self.skipTest("symlinks are not available here")
            rep = analyze(root)
        self.assertEqual(rep.files_scanned, 1)

    def test_exclude_patterns_skip_paths(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "vendor").mkdir()
            (root / "vendor" / "lib.py").write_text("x = 1\n")
            (root / "app.py").write_text("x = 2\n")
            rep = analyze(root, exclude=("vendor/*",))
        self.assertEqual([path.name for path in [Path("app.py")]], ["app.py"])
        self.assertEqual(rep.files_scanned, 1)

    def test_config_limits_are_used(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "pyproject.toml").write_text('[tool.pyproject-lens]\nmax_files = 1\n')
            (root / "a.py").write_text("x = 1\n")
            (root / "b.py").write_text("x = 2\n")
            with self.assertRaises(ScanningLimitExceeded):
                analyze(root)

    def test_config_exclude_is_used(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "pyproject.toml").write_text('[tool.pyproject-lens]\nexclude = ["vendor/*"]\n')
            (root / "vendor").mkdir()
            (root / "vendor" / "lib.py").write_text("x = 1\n")
            (root / "app.py").write_text("x = 2\n")
            rep = analyze(root)
        self.assertEqual(rep.files_scanned, 1)

    def test_cli_flags_override_config(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "pyproject.toml").write_text('[tool.pyproject-lens]\nexclude = ["vendor/*"]\n')
            (root / "vendor").mkdir()
            (root / "vendor" / "lib.py").write_text("x = 1\n")
            (root / "app.py").write_text("x = 2\n")
            rep = analyze(root, exclude=())
        self.assertEqual(rep.files_scanned, 2)

    def test_cli_scan_aborted_exit_code(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "a.py").write_text("x = 1\n")
            (root / "b.py").write_text("x = 2\n")
            err = io.StringIO()
            with redirect_stderr(err):
                code = main([str(root), "--max-files", "1"])
        self.assertEqual(code, 2)
        self.assertIn("SCAN ABORTED", err.getvalue())

    def test_node_modules_is_skipped_by_default(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "node_modules" / "pkg").mkdir(parents=True)
            (root / "node_modules" / "pkg" / "lib.py").write_text("x = 1\n")
            rep = analyze(root)
        self.assertEqual(rep.files_scanned, 0)


class SmarterRuleTests(unittest.TestCase):
    def test_requirements_txt_is_a_soft_declaration(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "app.py").write_text("import requests\n")
            (root / "requirements.txt").write_text("requests>=2.0  # pinned\n")
            rep = analyze(root)
        deps = next(sec for sec in rep.sections if sec.name == "Dependencies")
        self.assertTrue(all("not declared" not in item.message for item in deps.findings))
        self.assertEqual(deps.score, 85)
        self.assertTrue(any("requirements.txt" in item.message for item in deps.findings))

    @unittest.skipUnless(sys.version_info >= (3, 10), "match syntax needs 3.10")
    def test_match_statement_flags_old_requires_python(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "pyproject.toml").write_text('[project]\nrequires-python = ">=3.9"\n')
            (root / "app.py").write_text("def pick(x):\n    match x:\n        case 1:\n            return 'one'\n        case _:\n            return 'other'\n")
            rep = analyze(root)
        compat = next(sec for sec in rep.sections if sec.name == "Python compatibility")
        self.assertEqual(compat.score, 60)
        self.assertIn("app.py", compat.findings[0].path)

    def test_proper_floor_does_not_flag_plain_code(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "pyproject.toml").write_text('[project]\nrequires-python = ">=3.9"\n')
            (root / "app.py").write_text("print('hi')\n")
            rep = analyze(root)
        compat = next(sec for sec in rep.sections if sec.name == "Python compatibility")
        self.assertEqual(compat.score, 100)

    def test_upper_bound_only_specifier_is_handled(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "pyproject.toml").write_text('[project]\nrequires-python = "<3.12"\n')
            rep = analyze(root)
        compat = next(sec for sec in rep.sections if sec.name == "Python compatibility")
        self.assertEqual(compat.score, 85)

    def test_test_tooling_config_softens_no_tests_warning(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "pyproject.toml").write_text("[tool.pytest.ini_options]\ntestpaths = ['tests']\n")
            rep = analyze(root)
        testing = next(sec for sec in rep.sections if sec.name == "Testing")
        self.assertEqual(testing.score, 85)
        self.assertIn("test tooling", testing.findings[0].message)

    def test_entry_point_scripts_do_not_count_as_crowding(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for name in ("main.py", "cli.py", "manage.py"):
                (root / name).write_text("pass\n")
            for index in range(10):
                (root / f"mod{index}.py").write_text("pass\n")
            rep = analyze(root)
        structure = next(sec for sec in rep.sections if sec.name == "Project structure")
        self.assertFalse(any("application Python files" in item.message for item in structure.findings))

    def test_many_plain_modules_still_flag_crowding(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for index in range(11):
                (root / f"mod{index}.py").write_text("pass\n")
            rep = analyze(root)
        structure = next(sec for sec in rep.sections if sec.name == "Project structure")
        self.assertTrue(any("application Python files" in item.message for item in structure.findings))

    def test_scanning_limit_is_exported_for_tools(self) -> None:
        import pyproject_lens

        self.assertTrue(issubclass(ScanningLimitExceeded, RuntimeError))
        self.assertEqual(pyproject_lens.__version__, "0.7.0")
