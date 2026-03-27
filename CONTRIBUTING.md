# Contributing to au

`au` is a small local-first CLI. Keep changes sharp, observable, and easy to reason about.

## Before You Open A PR

- Check existing issues before filing a new one.
- Keep one concern per pull request when possible.
- Prefer changing local detection or rendering logic only when you can explain the user-visible effect.
- Do not add network dependencies or background services without a strong reason.

## Development Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

Useful commands:

```bash
make run
make test
make dist
```

## Project Shape

- `agent_usage_cli/`: detectors, models, rendering, CLI entrypoints
- `tests/`: unit coverage for parser and rendering behavior
- `docs/`: GitHub Pages site
- `scripts/build_zipapp.py`: single-file release artifact builder

## Change Expectations

- Add or update tests when behavior changes.
- Keep output stable unless the change is intentionally user-facing.
- Prefer explicit, human-readable CLI output over clever formatting.
- Update `README.md` and `docs/` when install, release, or user-facing behavior changes.

## Releases

Releases are tag-driven.

1. Bump `agent_usage_cli.__version__` in `agent_usage_cli/__init__.py`.
2. Verify `make test` and `make dist`.
3. Commit the release changes.
4. Create and push a tag like `v0.1.1`.

The release workflow publishes the `au` zipapp, the Debian package, and checksums.

## Project Site

The project site lives in `docs/` and deploys through `.github/workflows/pages.yml`.

In the GitHub repository settings, set Pages to use the GitHub Actions source so pushes to `main`
can publish the static site.
