# pyproject-lens

**Run one command. Get the useful stuff first.**

`pyproject-lens` is a small, free health scanner for Python projects. Give it a folder and it looks for the easy-to-miss things that slowly turn into annoying bugs: a dependency you forgot to declare, a Python version claim that is too old, an `.env` file that is not ignored, a project with no tests, or a package that is hard to install.

It is made for that first ten seconds when you open a project and think: *is this thing okay, or is it hiding problems?*

```bash
pip install pyproject-lens
pyproject-lens .
```

No account. No config maze. Normal scans never change files or upload code anywhere. The optional `--fix` command is the one exception, and it only applies the safe fixes listed below.

## What you get

The normal report is short and practical:

```text
DEPENDENCIES  90/100
  WARNING: 'requests' is imported but not declared.
    Try: Add it to project.dependencies if it is a runtime dependency.

PROJECT HEALTH: 82/100  |  3 warning(s)
```

When it can, it points to the file and line too:

```text
WARNING (src/app.py:12): 'requests' is imported but not declared.
```

The score is not a grade. It is a quick, predictable summary: every section starts at 100, the scanner deducts points only for checks it found, and the final health score is the average.

## Install

```bash
pip install pyproject-lens
```

Python 3.9 or newer is supported.

## Use it

Scan the current project:

```bash
pyproject-lens .
```

Run it as a module (works even when the console script is not on PATH):

```bash
python -m pyproject_lens .
```

Check the version:

```bash
pyproject-lens --version
```

Scan another folder:

```bash
pyproject-lens ./my-project
```

Save reports for CI, a code review, or later:

```bash
pyproject-lens . --json report.json
pyproject-lens . --markdown report.md
pyproject-lens . --html report.html
```

The HTML report is one standalone file. Open it in a browser or attach it to a project review.

### CI mode

Fail a job when the score is too low:

```bash
pyproject-lens . --ci --minimum-score 75
```

Or keep the threshold in `pyproject.toml`:

```toml
[tool.pyproject-lens]
minimum_score = 75
```

Then use:

```bash
pyproject-lens . --ci
```

### Safe fixes

Use `--fix` when you want the tool to make a small, deterministic fix:

```bash
pyproject-lens . --fix
```

Current fixes:

- **Missing `[project]` fields** — adds `project.name` (from the folder name), `project.version` (`0.1.0`), and `project.requires-python` (`>=3.9`) when they are absent, and adds `project.readme` only if a README file actually exists. Fields listed in `dynamic` are never touched.
- **`.env` not ignored** — adds `.env` to `.gitignore` when a `.env` file is present but not ignored.
- **No `.gitignore`** — creates a starter `.gitignore` (caches, virtualenvs, build output) for Git repositories that have none.

The guarantees:

- **Never overwrites.** Existing values, keys, and comments stay byte-for-byte identical; the fix only fills gaps.
- **Idempotent.** Running `--fix` twice changes nothing the second time.
- **Never guesses blindly.** If `pyproject.toml` cannot be parsed, it is left untouched.
- **Never edits Python source code, dependencies, or versions managed by dynamic tooling.**

You can call the same fixes from Python:

```python
from pyproject_lens import apply_safe_fixes

apply_safe_fixes("./my-project")
```

## Safety limits (no hangs, ever)

The scanner never walks a directory tree without bounds. It skips virtual environments, caches, build output, `node_modules`, and other non-project directories, never follows symlinked directories, and stops with a clear error instead of hanging when a tree is unusually large:

- **max 5,000 Python files** per scan
- **max 12 directory levels** deep

If a legitimate project hits a cap, raise it:

```bash
pyproject-lens . --max-files 20000 --max-depth 20
```

You can also skip parts of the tree:

```bash
pyproject-lens . --exclude "vendor/*" --exclude "scripts/*"
```

The exit code is `2` and the message starts with `SCAN ABORTED:` when a cap is hit, so CI jobs fail fast instead of timing out.

Or keep the limits in `pyproject.toml` (explicit flags win over the config):

```toml
[tool.pyproject-lens]
max_files = 20000
max_depth = 20
exclude = ["vendor/*", "examples/*"]
```

## What it checks

- **Packaging** — `pyproject.toml`, project name, supported Python version, and README basics.
- **Dependencies** — imports compared with `project.dependencies`, including common aliases such as `yaml` / `PyYAML`, `PIL` / `Pillow`, and `sklearn` / `scikit-learn`. Imports only listed in `requirements*.txt` get a gentle info note instead of a full warning. Local packages are never flagged.
- **Python compatibility** — syntax gated on the declared floor: `match`/`case` (3.10) and `type` aliases (3.12) are checked against a properly parsed lower bound from `requires-python`, not a naive regex.
- **Project structure** — `src/` layouts, packages, and root crowding that understands entry-point scripts (`app.py`, `manage.py`, `cli.py`...) and tooling files, so single-file Flask/Django apps are not scolded.
- **Testing** — test files, test tooling config (`[tool.pytest]`, `tox.ini`, `noxfile.py`), and a test-to-source ratio that is reported as info, never claimed as coverage.
- **Security basics** — possible hard-coded secrets, `eval`, `exec`, `shell=True`, and `.env` files not clearly ignored.
- **Documentation** — README, install and usage hints, license, and contribution guide.
- **Git hygiene** — `.gitignore` and uncommitted changes when the folder is a Git repository.

This tool does not replace Ruff, pytest, Bandit, a dependency vulnerability scanner, or a human review. It is the friendly first pass before those tools.

## Configuration reference

Everything lives under `[tool.pyproject-lens]` in your `pyproject.toml`:

| Key              | Type            | Default | Meaning                                        |
| ---------------- | --------------- | ------- | ---------------------------------------------- |
| `minimum_score`  | int             | `0`     | Threshold used by `--ci`                       |
| `max_files`      | int             | `5000`  | Safety cap on scanned Python files             |
| `max_depth`      | int             | `12`    | Safety cap on directory depth                  |
| `exclude`        | list of strings | `[]`    | Glob patterns skipped during the scan          |

Command-line flags override the config file.

## Python API

Use the same scanner from your own script:

```python
from pyproject_lens import analyze

report = analyze("./my-project")
print(report.score)
print(report.to_json())
report.to_html("report.html")
```

The API is read-only and raises `pyproject_lens.analyzers.ScanningLimitExceeded` if the tree is too large, so interactive tools can fail fast. The one exception is `apply_safe_fixes()`, which writes files exactly like `--fix` does.

## Integrations

### GitHub Actions

```yaml
name: project-health
on: [push, pull_request]
jobs:
  lens:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - run: pip install pyproject-lens
      - run: pyproject-lens . --ci --minimum-score 70
```

### Pre-commit hook

Save this as `.git/hooks/pre-commit` (and `chmod +x` it):

```bash
#!/bin/sh
pyproject-lens . --ci --minimum-score 60 || echo "pyproject-lens: health below threshold"
```

(Or wire the same command into your pre-commit framework config.)

### VS Code / PyCharm

Run it as an external tool and jump to findings, since every warning carries `file:line` locations:

```text
pyproject-lens $ProjectFileDirectory$ --json -
```

## Why it is free

This project is MIT licensed and open source. All current features are free. The goal is to make a tool developers can run on any project without signing up for anything.

## Development

```bash
python -m pip install -e .
python -m unittest discover -s tests
python -m build
```

Contributions are welcome. Keep checks useful, keep messages honest, and add a small test when fixing a bug.

## Author

**Samarth Chugh** — GitHub: [@Sam3360](https://github.com/Sam3360)
