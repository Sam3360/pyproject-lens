# Contributing

Thanks for helping out.

Keep changes small and useful. A check should explain what it found, suggest a practical next step, and avoid acting more certain than static analysis really is.

Before opening a pull request, run:

```bash
python -m unittest discover -s tests
python -m build --no-isolation
```

If you add a check, add a small test for it too.
