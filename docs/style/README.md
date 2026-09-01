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

## Package `__init__.py` re-export convention

Every package under `src/reflow` whose contents are meant to be imported by *other*
packages re-exports its full public surface from `__init__.py`: an explicit
`from reflow.<pkg>.<module> import ...` block per submodule, followed by an `__all__`
listing every re-exported name. `src/reflow/policy/__init__.py` is the canonical shape to
copy. Two mechanical rules keep this consistent and `ruff`-enforced rather than a matter
of taste:

- Names within one `from ... import (...)` block, and within `__all__` itself, are ordered
  by `ruff`'s `isort` (`I`) and `RUF022` rules: `ALL_CAPS` constants first, then `PascalCase`
  classes, then `lower_snake_case` functions, alphabetical within each group. Running
  `ruff check --fix` / `ruff format` on a package's `__init__.py` after editing it produces
  the correct order mechanically; nobody hand-sorts this.
- When two submodules in the same package independently define a same-named, generic
  helper (most commonly a `to_dict` serialiser), the re-export is renamed at the package
  boundary with a type-specific prefix instead of one silently shadowing the other —
  e.g. `reflow.policy` re-exports `policy.decision.to_dict` as `decision_to_dict`, and
  `reflow.audit` re-exports `audit.record.to_dict` as `audit_record_to_dict`. When the
  collision is between two *modules'* entire same-named export sets rather than one
  function (as happens between `reflow.eval.clustering` and `reflow.eval.incident`, which
  independently define `Provenance`, `to_json_dict`, `to_markdown`, `DEFAULT_SEED`, and
  `DEFAULT_N_EVENTS`), the whole second module's re-exports take a module-name-derived
  prefix instead — see `reflow.eval`'s own `__init__.py` docstring for the worked example.

As of 2026-09-01, every package that is not frozen evaluation corpus/taxonomy data follows
this convention: `taxonomy`, `corpus`, `signature`, `cluster`, `incident`, `diagnose`,
`policy`, `eval`, `llm`, `execute`, `audit`, `outcome`, and `webhook` all re-export a full
surface. (`execute`, `audit`, `outcome`, and `webhook` did not until an adversarial review
on this date found the split indefensible — `from reflow.execute import BoundedExecutor`
raised `ImportError` while the equivalent worked for `policy`, with no principled reason
for the difference; see `BUILD_LOG.md`, 2026-09-01.)

Two packages deliberately do not: `demo` and `report`. Both are leaf CLI entry points, not
libraries other packages build on. Every consumer of either — `reflow.cli`, each package's
own test suite, and `reflow.report.data`'s own read of `reflow.demo.data`'s path constants
— already imports directly from the specific submodule it needs
(`reflow.demo.data.load_demo_data`, `reflow.report.html.build_report_html`, and so on), and
`reflow.report` additionally ships a `__main__.py`, making `python -m reflow.report` a
second, independent piece of evidence that it is consumed as a script, not a library
surface. A package-level re-export here would have zero real callers and would just be
surface area to keep in sync for its own sake. If a future phase adds a second consumer
that wants `from reflow.demo import X` or `from reflow.report import Y`, add the surface
then, in the same shape as every other package.
