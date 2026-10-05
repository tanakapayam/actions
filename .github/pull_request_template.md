## What and why

<!-- What failed, or what was missing? How would a test have caught it? -->

## Checklist

- [ ] `uv run pytest`, `ruff`, `mypy` pass; `actionlint` and `zizmor` are clean
- [ ] Docs are updated (`uv run python scripts/render_reference.py`), and so are the README and CHANGELOG
- [ ] An input or output of a released action changed? The CHANGELOG says so first
- [ ] A new or changed action has a `dogfood` step in `ci.yml`
