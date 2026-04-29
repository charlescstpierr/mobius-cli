# AGENTS.md

Conventions partagées que les agents de codage (Droid, Claude Code, Codex, etc.) doivent connaître pour travailler dans ce repo.

## Agent skills

### Issue tracker

Issues et PRD vivent comme des fichiers markdown sous `.scratch/<feature>/`. Voir `docs/agents/issue-tracker.md`.

### Triage labels

Vocabulaire canonique par défaut (`needs-triage`, `needs-info`, `ready-for-agent`, `ready-for-human`, `wontfix`), inscrit en front-matter `Status:` des fichiers d'issues. Voir `docs/agents/triage-labels.md`.

### Domain docs

Layout single-context (`CONTEXT.md` + `docs/adr/` à la racine du repo). Voir `docs/agents/domain.md`.
