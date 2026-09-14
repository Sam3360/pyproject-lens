# pyproject-lens

A small, free health scanner for Python projects. Point it at a folder and it checks the basics: packaging metadata, imports versus declared dependencies, Python-version claims, project layout, tests, obvious security footguns, documentation, and Git hygiene.

It is built for the first ten seconds of project review — not to replace Ruff, pytest, Bandit, or a human code review.

## Install

```bash
pip install pyproject-lens
```

## Use it

```bash
pyproject-lens .
pyproject-lens ./another-project --json report.json
pyproject-lens . --markdown report.md
pyproject-lens . --html report.html
pyproject-lens . --ci --minimum-score 75
```

You can also use it in Python:

```python
from pyproject_lens import analyze

report = analyze(".")
print(report.score)
print(report.to_json())
```

## What the score means

Each section starts at 100. Detected issues reduce only the relevant section, and the project score is the rounded average. The rules are deliberately simple and visible in `src/pyproject_lens/analyzers.py`; it is a conversation starter, not a grade.

## What it checks

- Packaging: `pyproject.toml`, project name, Python version, README
- Dependencies: direct source imports compared with `project.dependencies`
- Compatibility: detects `match/case` used with a Python claim below 3.10
- Structure: `src/`, packages, root modules, and tests directory
- Testing: test file presence and a rough source-to-test-file signal — not coverage
- Security: possible hard-coded secrets, `eval`/`exec`, and `shell=True`
- Documentation: README, install/usage wording, license, and contribution guide
- Repository hygiene: `.gitignore` and uncommitted changes
- Reports: terminal, JSON, Markdown, and a standalone HTML file

Everything is free and open source under the MIT license.

## Development

```bash
python -m pip install -e .
python -m unittest discover -s tests
```

Contributions are welcome. Please keep checks practical, explain what they found, and avoid claiming certainty when static analysis cannot prove something.
