# Mobius project types

Mobius tracks acceptance-criteria for many kinds of projects. Each project
type has a built-in template you can apply with `mobius init --template <name>`
or `mobius interview --template <name>`. Without `--template`, Mobius
auto-detects the type from the manifests it finds in the cwd
(`package.json`→web, `Cargo.toml`→cli, `pyproject.toml`→lib, `mkdocs.yml`
or `docs/index.md`→docs, `pubspec.yaml` or `ios/`+`android/`→mobile, otherwise
`blank`).

> Reminder: **Mobius does not execute commands.** It records criteria and
> stamps every run with events so you can replay the lineage. The `command:`
> fields below are **descriptive metadata**; you (or your agent or CI) are
> responsible for actually running them.

## A — Web app (Next.js / SPA)

```yaml
# mobius init --template web
project_type: greenfield
template: web
goal: Ship a web app preview deploy with passing lint, typecheck, build, and e2e tests.
constraints:
  - All scripts must exit 0
  - Preview URL must be reachable
success_criteria:
  - lint passes (npm run lint)
  - typecheck passes (npm run typecheck)
  - build succeeds (npm run build)
  - e2e tests pass (npm run e2e)
  - preview deploy URL emitted
steps:
  - name: lint
    command: npm run lint
  - name: typecheck
    command: npm run typecheck
  - name: build
    command: npm run build
  - name: e2e
    command: npm run e2e
  - name: deploy
    command: npm run deploy:preview
```

## B — CLI tool (Rust / Go / Python)

```yaml
# mobius init --template cli
project_type: greenfield
template: cli
goal: Release a CLI binary with formatted, lint-clean, tested, and built artifacts.
constraints:
  - Toolchain pinned and reproducible
  - Release artifact must be a single self-contained binary
success_criteria:
  - fmt check passes
  - lint passes with warnings as errors
  - unit tests pass
  - release build produces the binary
  - release artifact uploaded
```

## C — Library publish (PyPI / npm / crates.io)

```yaml
# mobius init --template lib
project_type: greenfield
template: lib
goal: Publish a library to its registry with quality gates and dual-format artifacts.
constraints:
  - Strict typing required
  - Distribution metadata must validate before upload
success_criteria:
  - linter passes on src/ and tests/
  - type checker passes on src/
  - test suite passes with required coverage
  - package builder produces sdist + wheel
  - metadata validation passes
```

## D — ETL pipeline (extract → transform → load → validate)

ETL projects benefit most from `steps:` and `depends_on:` because each
stage produces an artifact the next stage consumes. Mobius doesn't run
the scripts, but it records the intended ordering so agents and dashboards
can show a real pipeline view.

```yaml
# mobius init --template etl
project_type: greenfield
template: etl
goal: Run nightly ETL pipeline producing validated load artifacts.
constraints:
  - Each stage writes its intermediate artifact under data/
  - Stages run sequentially; downstream depends on upstream
  - Total runtime budget 30 minutes
success_criteria:
  - extract stage produces data/raw.json
  - transform stage produces data/clean.json
  - load stage produces data/loaded.json
  - validate stage produces data/validation.txt
steps:
  - name: extract
    command: ./extract.sh
  - name: transform
    command: ./transform.sh
    depends_on:
      - extract
  - name: load
    command: ./load.sh
    depends_on:
      - transform
  - name: validate
    command: ./validate.sh
    depends_on:
      - load
```

## E — Mobile app (iOS + Android matrix)

Mobile builds are inherently multi-axis. Mobius accepts a `matrix:` block:

```yaml
# mobius init --template mobile
project_type: greenfield
template: mobile
goal: Ship a mobile app to internal track on iOS and Android.
constraints:
  - Both platforms must build cleanly
  - Internal track upload required for each platform
success_criteria:
  - dependencies fetched
  - static analysis passes (no errors)
  - test suite passes
  - Android APK built
  - iOS IPA built
  - Android uploaded to internal track
  - iOS uploaded to internal track
matrix:
  platform:
    - ios
    - android
steps:
  - name: deps
    command: make deps
  - name: analyze
    command: make analyze
  - name: test
    command: make test
  - name: build_android
    command: make build-android
  - name: build_ios
    command: make build-ios
  - name: upload_android
    command: make upload-android
  - name: upload_ios
    command: make upload-ios
```

## F — Markdown docs site (mkdocs / Docusaurus)

```yaml
# mobius init --template docs
project_type: greenfield
template: docs
goal: Build and deploy versioned product documentation site.
constraints:
  - Markdown sources under docs/
  - All internal links must resolve
success_criteria:
  - spell check finds no errors
  - link check passes
  - diagram render passes
  - site builds (output produced)
  - preview deployed
```

## Auto-detection

When you run `mobius init` without `--template`, Mobius inspects the cwd:

| Detected file | Template chosen |
| --- | --- |
| `pubspec.yaml` or `ios/` + `android/` | `mobile` |
| `mkdocs.yml` or `docs/index.md` | `docs` |
| `pyproject.toml` | `lib` |
| `Cargo.toml` | `cli` |
| `package.json` | `web` |
| `dbt_project.yml` or `airflow.cfg` | `etl` |
| (none of the above) | `blank` |

The output of `mobius init` always prints the template that was applied
and whether it was auto-detected, so you can correct course immediately.
