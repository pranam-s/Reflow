# Style references

This is an index of the external references this project's style rules are built on.
Each entry links to the source and states, in one line, how it applies in `reflow`.

- [PEP 8](https://peps.python.org/pep-0008/) — general Python style baseline; enforced
  mechanically here by `ruff check` (rule set `E`, `F`, `I`, `N`, `UP`, `B`, `SIM`, `C4`,
  `RET`) and `ruff format`, so PEP 8 compliance is a CI gate, not a convention to remember.
- [PEP 257](https://peps.python.org/pep-0257/) — docstring conventions; this project
  requires a docstring on every module, class, function, and method (see `CLAUDE.md`),
  checked by `ruff`'s `D` rules with the `google` convention.
- [PEP 484](https://peps.python.org/pep-0484/) — type hint semantics; every function
  signature in `src/reflow` is fully annotated and checked with `mypy --strict`, which is
  a blocking CI gate.
- [Google Python Style Guide](https://google.github.io/styleguide/pyguide.html) — the
  concrete docstring format used throughout (`Args:` / `Returns:` / `Raises:` sections),
  matching `ruff`'s `pydocstyle` `convention = "google"` setting.
- [pytest good practices](https://docs.pytest.org/en/stable/explanation/goodpractices.html)
  — this project uses the recommended `src` layout with `--import-mode=importlib`, and
  tests mirror the `src/reflow` package structure under `tests/`.
- [Conventional Commits](https://www.conventionalcommits.org/en/v1.0.0/) — every commit
  message in this repository follows this format (`feat:`, `fix:`, `chore:`, ...).
- [Keep a Changelog](https://keepachangelog.com) — once the project has user-facing
  behavior worth logging, `CHANGELOG.md` will follow this format; not needed at Phase 0.
- [SemVer](https://semver.org) — `reflow.__version__` and the `pyproject.toml` project
  version follow semantic versioning as features land.
