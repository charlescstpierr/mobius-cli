# Interview v2 — Skill unifié avec modes quick/deep

## Résumé

Upgrade du skill `/interview` Mobius pour intégrer deux modes : **deep** (défaut) et **quick** (opt-out). Le mode deep fusionne les meilleures mécaniques du skill `/entrevue` (scoring, anti-complaisance, pre-mortem, branches) tout en produisant le même artefact : un `spec.yaml` enrichi consommable par `mobius seed`.

**Contrainte :** le skill `/entrevue` global (`~/.claude/skills/entrevue/`) reste intact et indépendant.

## Décisions verrouillées

| Décision | Choix |
|----------|-------|
| Emplacement | `src/mobius/integration/assets/skills/interview/skill.md` (skill Mobius intégré) |
| Mode par défaut | `deep` — l'utilisateur tape `/interview quick` pour l'opt-out |
| Output | `spec.yaml` enrichi uniquement — pas de fichier `Entrevue.md` |
| Mécaniques deep | Les 10 mécaniques d'`/entrevue` sont gardées |
| Champs spec.yaml | Nouvelles clés ajoutées à `ALLOWED_KEYS` dans `seed.py` (option A) |
| Architecture skill | Approche 2 — fichier unique avec sections conditionnelles (~350 lignes) |
| Écriture métadonnées | Flag CLI `--deep-metadata deep-meta.json` — Python gère la sérialisation |
| `/entrevue` | Inchangé — reste disponible globalement hors pipeline Mobius |

## Architecture

### Structure fichier

```
src/mobius/integration/assets/skills/interview/
  skill.md          ← skill v2 (~350 lignes, sections quick + deep)
```

### Routing

| Invocation | Mode |
|------------|------|
| `/interview` | deep |
| `/interview deep` | deep |
| `/interview quick` | quick |
| `/interview <goal text>` | deep (le texte est affiché comme contexte initial — futur, nécessite changement CLI) |

### Flux

```
/interview
┌──────────────────────────────────────┐
│  --quick               --deep        │
│                                      │
│  Phase 1: scan         Phase 1: scan │
│  Phase 2: conversation Phase 2: vision + cartographie │
│  Phase 3: extract CLI  Phase 3: exploration branches  │
│     │                  Phase 4: challenge + pre-mortem │
│     │                  Phase 5: extraction → CLI       │
│     │                     │                            │
│     └─────────┬───────────┘                            │
│               ▼                                        │
│   mobius interview --non-interactive                   │
│               ▼                                        │
│           spec.yaml (base)                             │
│               ▼ (deep only)                            │
│   mobius interview --deep-metadata deep-meta.json      │
│   → Python merge + validate → spec.yaml final          │
└──────────────────────────────────────┘
```

## Mode Quick

Identique au skill `/interview` actuel. Conversation légère (~5 min) pour extraire :

1. **Goal** — une phrase
2. **Constraints** — liste d'invariants
3. **Success criteria** — résultats mesurables
4. **Project type** — greenfield/brownfield
5. **Context** — brownfield uniquement

Résumé → confirmation → `mobius interview --non-interactive` → `spec.yaml`.

## Mode Deep

### Phase 1 — Vision

- Demander de présenter le projet en quelques phrases
- Détecter le type de plan :
  - business/startup, produit/app, événement/projet perso, carrière/formation, créatif/contenu, communauté/open-source, infrastructure/ops, juridique/compliance, autre/hybride
- Détecter la maturité : idée brute, plan esquissé, plan détaillé
- Reformuler et vérifier l'alignement (max 2 tentatives, puis choix A/B)
- Si domaine sensible (santé, juridique, finance) → avertissement immédiat
- **Gate :** l'utilisateur confirme la reformulation

### Phase 2 — Cartographie

- 2-3 questions ouvertes pour comprendre les composantes
- Dessiner l'arbre de branches avec statuts :
  - `[ ]` non explorée, `[~]` en cours, `[✓]` résolue, `[!]` non résolu, `[pause]` en pause
- **Gate :** l'utilisateur valide l'arbre, minimum 2 branches

### Phase 3 — Exploration (branche par branche)

**Format par tour :**
1. Ciblage interne (axe le plus bas + pourquoi c'est le goulot)
2. Question nue — une seule, puis attendre
3. Réaction — avis franc, patterns BAD/GOOD si applicable, red flags
4. Scoring : `Objectif X/5 (=) | Comment X/5 (+1: raison) | Critères X/5 (-1: raison)`

**Mécaniques intégrées :**

- **Anti-complaisance** — patterns BAD/GOOD contrastifs, jamais "c'est intéressant" ou "bonne réponse"
- **Push twice** — la première réponse aux forcing questions est souvent la version polie, pousser une deuxième fois. Jamais plus de 2 fois.
- **Routage par question** — `[fait-auto]`, `[fait-confirm]`, `[décision]`, `[recherche]`
- **Smart-skip** — si la réponse contient chiffre + nom + exemple concret, sauter. Exception : forcing questions jamais skippées.
- **Forcing questions par domaine** — questions spécifiques selon le type détecté en Phase 1
- **Registre de concepts** — termes importants avec définitions, détection de contradictions
- **Résumé** après chaque branche complétée

**Sous-phases conditionnelles :**

- **Phase 3.5 — Changement de perspective** (sur signal : blocage 3+ tours, complexité galopante, tout trop facile) — modes Contrarian, Simplificateur, Recentreur, Utilisateur Final, Concurrent
- **Phase 3.7 — Recherche web** (sur déclencheur : chiffre non sourcé, concurrent ignoré, faisabilité incertaine) — analyse 3 couches + eureka check

**Gate :** aucune branche `[ ]` ou `[~]` dans le registre

### Phase 4 — Challenge

- Lister les hypothèses cachées (marché, ressources, comportements, technique, timing)
- **Pre-mortem obligatoire** : "Dans 1 an ça a échoué. Pourquoi ?"
- **Phase 4.5 — Deuxième opinion** (sous-agent avec 4 questions : élément solide, élément risqué, angle mort, test faisable en 48h)
- Si un axe tombe sous 4/5 → retour en Phase 3 sur les branches impactées

**Gate :** total >= 12/15, chaque axe >= 4/5

### Phase 5 — Extraction → spec.yaml

**Checklist de fin (toutes requises) :**
- [ ] Branches : toutes `[✓]` ou `[!]`
- [ ] Hypothèses : listées et validées
- [ ] Pre-mortem : scénario d'échec discuté
- [ ] Challenge : au moins un pattern BAD/GOOD utilisé OU un changement de perspective déclenché
- [ ] Clarté : total >= 12/15 ET chaque axe >= 4/5
- [ ] Actions : prochaines étapes identifiées

**Mapping entrevue → spec.yaml :**

| Donnée deep mode | Champ spec.yaml |
|------------------|----------------|
| Vision synthétisée + branches | `goal` |
| Invariants identifiés + hypothèses validées | `constraints` |
| Critères mesurables (palier 4+ du scoring) | `success_criteria` |
| Contexte existant (brownfield) | `context` |
| Score de clarté 3 axes | `clarity_score` |
| Risques identifiés | `risks` |
| Hypothèses validées/invalidées | `assumptions` |
| Scénario d'échec | `premortem` |
| Nombre de branches explorées | `branches_explored` |
| Termes clés + définitions | `concepts` |
| "deep" | `interview_mode` |

**Mécanisme d'écriture (mode deep) :**

1. Le skill écrit un fichier JSON temporaire `deep-meta.json` avec les métadonnées deep
2. Le skill appelle `mobius interview --non-interactive --deep-metadata deep-meta.json`
3. Python (`interview.py`) lit le JSON, valide les types, merge dans le spec.yaml
4. Le spec.yaml final est atomiquement écrit avec tous les champs
5. L'event store enregistre les métadonnées deep via `interview.completed`

**Gate d'ambiguïté en mode deep :** le gate Python (`compute_ambiguity_score`, seuil 0.2) reste actif mais ne devrait jamais échouer — le mode deep produit des réponses de haute qualité par construction (scoring >= 12/15). Si le gate échoue malgré tout, le skill affiche l'erreur et propose de reformuler les champs problématiques avant de réessayer.

## Scoring de clarté

Trois axes, chacun noté de 0 à 5 :

### Objectif (la destination)

| Palier | Critère factuel |
|--------|----------------|
| 0 | Pas encore discuté |
| 1 | Aucun qui/quoi/pourquoi identifiable |
| 2 | Qui OU quoi identifié, pas les deux |
| 3 | Qui + quoi + pourquoi identifiés |
| 4 | Au moins 2 métriques chiffrées |
| 5 | Métriques testées sur des vrais utilisateurs |

### Comment (le chemin)

| Palier | Critère factuel |
|--------|----------------|
| 0 | Pas encore discuté |
| 1 | Aucune étape concrète |
| 2 | Étapes nommées sans dates ni responsables |
| 3 | Étapes + responsables OU dates |
| 4 | Étapes + responsables + dates + budget |
| 5 | Preuves d'exécution (artefacts, commits) |

### Critères (la réussite)

| Palier | Critère factuel |
|--------|----------------|
| 0 | Pas encore discuté |
| 1 | Aucun critère mesurable |
| 2 | Critère nommé mais non mesurable |
| 3 | Au moins 1 critère mesurable |
| 4 | Au moins 2 critères mesurables avec seuils |
| 5 | Critères mesurés sur données réelles |

**Ciblage :** prochaine question → axe le plus bas. Égalité → Critères > Objectif > Comment.

**Règles :** le score monte sur preuve factuelle, baisse sur contradiction/invalidation. Baisse forcée de 2+ si une prémisse de Phase 4 invalide une branche complète.

## Spec.yaml enrichi

```yaml
# --- champs standards (mode quick ET deep) ---
session_id: interview_mon-projet_abc123
project_type: brownfield
template: cli
ambiguity_score: 0.05
ambiguity_gate: 0.2
ambiguity_components:
  goal: 0.0
  constraints: 0.0
  success: 0.0
goal: "Unifier le skill interview avec modes quick/deep"
constraints:
  - "Rétrocompatible avec mobius seed"
  - "Un seul fichier skill.md"
success_criteria:
  - "Score de clarté >= 12/15 en mode deep"
  - "Mode quick produit spec.yaml en < 5 min"
context: "Skill interview existant + skill entrevue séparé"

# --- champs deep mode (ajoutés après l'appel CLI) ---
interview_mode: deep
clarity_score:
  objectif: 5
  comment: 4
  criteres: 4
  total: 13
risks:
  - description: "Le skill de 350 lignes peut perdre l'agent en contexte"
    severity: medium
  - description: "Le mode deep fatigue l'utilisateur sur des projets simples"
    severity: low
assumptions:
  - statement: "Le gate d'ambiguïté Python ne bloque jamais après un deep interview"
    status: validated
  - statement: "Le YAML parser supporte les structures deep (depth <= 4)"
    status: validated
premortem: "Échec si le mode deep fatigue l'utilisateur"
branches_explored: 4
concepts:
  - term: "mode deep"
    definition: "Interview structuré avec scoring et challenge"
  - term: "mode quick"
    definition: "Extraction rapide sans challenge"
```

## Changements Python

### `src/mobius/workflow/seed.py`

Ajouter à `ALLOWED_KEYS` :

```python
"interview_mode",
"clarity_score",
"assumptions",
"premortem",
"branches_explored",
"concepts",
```

Le champ `risks` est déjà dans `ALLOWED_KEYS` avec normalisation `_normalize_mapping_list` (liste de dicts). Les champs deep doivent utiliser le même pattern — c'est pourquoi `assumptions` et `concepts` sont des listes de dicts, pas des dicts imbriqués.

Ajouter les champs deep au dataclass `SeedSpec` (tous optionnels, défauts vides) et à `to_event_payload()` pour qu'ils soient persistés dans l'event store.

Ajouter la normalisation dans `validate_seed_spec` :
- `clarity_score` → `_normalize_metadata` (dict string→string)
- `assumptions` → `_normalize_mapping_list` (liste de dicts)
- `concepts` → `_normalize_mapping_list` (liste de dicts)
- `premortem` → `_as_text` (string)
- `branches_explored` → `_as_int` (int)
- `interview_mode` → `_as_text` (string)

### `src/mobius/workflow/interview.py`

Ajouter un paramètre `deep_metadata_path: Path | None` à `render_spec_yaml()`. Si fourni, lire le JSON, valider les types, et inclure les champs dans le YAML généré. Pas d'append post-hoc — écriture atomique unique.

### `src/mobius/cli/commands/interview.py`

Ajouter un flag CLI `--deep-metadata <path>` (optionnel). Passe le chemin à `render_spec_yaml()`.

### Tests

- **Golden test mode quick** : le spec.yaml produit est identique à l'actuel (non-régression)
- **Golden test mode deep** : spec.yaml enrichi passe `load_seed_spec()` sans erreur
- **Test rejet** : deep metadata invalide (mauvais types, clés manquantes) → erreur claire
- **Test YAML parser** : valider que `_parse_simple_yaml` parse correctement les structures deep (listes de dicts sous top-level key)

## Règles du skill

- **Une question à la fois** en mode deep
- **Français par défaut**, termes anglais courants gardés
- **Jamais de MCP** — Mobius est un CLI, toujours via Bash
- **Sortie anticipée** : si l'utilisateur dit "assez", montrer la checklist + statut INCOMPLET. S'il insiste → synthèse immédiate et extraction partielle.
- **Progression affichée** après chaque branche : `X/Y branches — Scoring: ...`
