---
name: interview
description: "Drive the user through a project-discovery conversation, then record the resulting spec via mobius interview --non-interactive. Two modes: deep (default) — structured interview with scoring, anti-complacency, and pre-mortem; quick — fast extraction for clear projects. Triggers: interview, start project, set up project, build X, track this work."
---

# Interview

Mobius does not call any LLM. **You** (the agent) hold the conversation; once
you have enough information, you invoke `mobius interview` via the **Bash
tool** with extracted parameters. Mobius records the spec and emits events.

> **Never** invoke Mobius via MCP. Mobius has no MCP server. Always use the
> `Bash` tool with the `mobius` shell command.

## When to use

Use whenever the user wants to start a new project (greenfield) or describe
an existing one (brownfield) for tracking. Typical triggers:

- "Help me set up this project."
- "I want to build X."
- "Use Mobius to track this work."
- "/interview" (slash command).

Do **not** use this skill to merely list `mobius` commands; use the `help`
skill for that.

## Workspace scan

Before talking, scan the cwd to detect the project type. Mobius will
auto-detect with `detect_template`, but knowing the type up front lets you
ask better follow-ups.

| File found | Likely template |
| ---------- | --------------- |
| `package.json` | `web` |
| `Cargo.toml` | `cli` |
| `pyproject.toml` | `lib` |
| `pubspec.yaml` or `ios/`+`android/` | `mobile` |
| `mkdocs.yml` or `docs/index.md` | `docs` |
| `dbt_project.yml` or `airflow.cfg` | `etl` |
| nothing recognisable | `blank` (greenfield) |

If a manifest exists, read it to learn the project name, scripts, and existing
dependencies. Reference them in your follow-up questions instead of asking the
user from scratch.

Si le template détecté ne correspond pas au projet que l'utilisateur décrit (ex: workspace Python mais projet Rust), utiliser le template correspondant à l'intent de l'utilisateur, pas au workspace.

## Mode routing

| Invocation | Mode |
|------------|------|
| `/interview` | deep |
| `/interview deep` | deep |
| `/interview quick` | quick |
| `/interview <goal text>` | deep (texte affiché comme contexte initial) |

---

# Mode Quick

> Use when: the user explicitly types `/interview quick`, the project is
> crystal-clear, or the user has already written a one-paragraph spec.

## Step-by-step

### 1. Scan the workspace (see table above)

### 2. Hold the conversation

Ask, in your own words and at your own pace, until you have:

1. **Goal** — one sentence describing what the project should ship.
2. **Constraints** — invariants the work must respect (perf, deps, deploy
   target, regulatory, "no breaking changes", etc.).
3. **Success criteria** — testable outcomes. Push for measurable ones
   (Lighthouse >= 90, coverage >= 95%, p95 < 200ms…).
4. **Project type** — `greenfield` (new) or `brownfield` (existing).
5. **(Brownfield only) context** — what existing system must be preserved.

Keep it conversational. Do not interrogate. Summarise back to the user
before moving to step 3.

### 3. Extract → invoke `mobius interview`

Once the user confirms, call:

```text
Bash('mobius interview --non-interactive \
  --template <web|cli|lib|etl|mobile|docs|blank> \
  --project-type <greenfield|brownfield> \
  --goal "<one sentence>" \
  --constraint "<constraint 1>" \
  --constraint "<constraint 2>" \
  --success-criterion "<criterion 1>" \
  --success-criterion "<criterion 2>" \
  [--context "<existing-system context>"] \
  --output spec.yaml')
```

Pass each constraint and each success criterion as its **own**
`--constraint` / `--success-criterion` flag. Quote values that contain
spaces. Mobius writes `spec.yaml` and a session id to stdout.

**Note :** le CLI applique un gate d'ambiguïté (seuil 0.2). Si le goal ou les critères sont trop vagues (ex: 'TBD', vides), le CLI rejettera la spec. Reformuler les champs problématiques et réessayer.

### 4. Hand back, then drive `mobius seed` / `run`

Show the user the path to `spec.yaml`, then offer the next action:

```text
Bash('mobius seed spec.yaml')
Bash('mobius run --spec spec.yaml')
Bash('mobius status <run_id> --follow')
```

## Worked example (quick)

User: *"I want to build a Next.js dashboard for tracking sales, with auth.
Deploys to Vercel. Must hit Lighthouse 90+."*

You inspect the cwd, find a `package.json` with `"next"`, ask one
follow-up ("Any auth provider preference?"), then call:

```text
Bash('mobius interview --non-interactive \
  --template web \
  --project-type greenfield \
  --goal "Ship a Next.js sales dashboard with auth deployed to Vercel" \
  --constraint "Deploy target is Vercel" \
  --constraint "Use NextAuth.js for authentication" \
  --success-criterion "Lighthouse score >= 90 on the dashboard route" \
  --success-criterion "Auth flow works end-to-end" \
  --success-criterion "Vercel preview deploy succeeds" \
  --output spec.yaml')
```

---

# Mode Deep (défaut)

> Ce mode est le défaut. Il conduit un entretien structuré en 5 phases avec
> scoring de clarté, anti-complaisance, et pre-mortem. Il produit un
> `spec.yaml` enrichi consommable par `mobius seed`.
>
> **Une question à la fois. Attendre la réponse avant de continuer.**
> **Français par défaut. Termes anglais courants gardés.**

---

## Phase 1 — Vision

### 1.1 Présentation initiale

Demander à l'utilisateur de présenter le projet en quelques phrases :

> "Présente-moi ton projet en quelques phrases — ce que tu veux accomplir,
> pour qui, et pourquoi maintenant."

### 1.2 Détection du type de plan

Après la présentation, détecter le type parmi :

| Type | Signaux clés |
|------|-------------|
| `business/startup` | marché, clients, revenus, CA, scale |
| `produit/app` | features, UX, déploiement, roadmap |
| `événement/projet-perso` | date, lieu, participants, logistique |
| `carrière/formation` | compétences, emploi, certifications, transition |
| `créatif/contenu` | audience, publication, style, médias |
| `communauté/open-source` | contributeurs, licence, adoption, gouvernance |
| `infrastructure/ops` | uptime, pipelines, scalabilité, migrations |
| `juridique/compliance` | régulation, conformité, audit, risques légaux |
| `autre/hybride` | combinaison ou ne rentre dans aucune catégorie |

### 1.3 Détection de la maturité

| Niveau | Signaux |
|--------|---------|
| `idée brute` | pas de plan, vague, "j'aimerais faire" |
| `plan esquissé` | quelques éléments définis, direction claire |
| `plan détaillé` | étapes, ressources, contraintes déjà identifiées |

### 1.4 Reformulation

Reformuler le projet en une phrase courte et vérifier l'alignement :

> "Si je comprends bien : [reformulation]. C'est ça ?"

- Si l'utilisateur dit non → reformuler à nouveau (max 2 tentatives).
- Après 2 échecs → proposer deux options A/B : "Est-ce plutôt A [option A]
  ou B [option B] ?"

Si le projet est brownfield (système existant) — poser explicitement : « Quel système existant doit être préservé ? Qu'est-ce qui ne doit surtout pas casser ? »

### 1.5 Avertissement domaine sensible

Si le domaine est santé, juridique, ou finance :

> "Attention : ce projet touche un domaine sensible ([santé/juridique/finance]).
> Je vais travailler avec toi pour clarifier le périmètre, mais je ne fournis
> pas de conseil médical, légal ou financier. Continue en gardant ça en tête."

### 1.6 Gate Phase 1

L'utilisateur confirme la reformulation avant de passer à la Phase 2.

---

## Phase 2 — Cartographie

### 2.1 Questions d'ouverture

Poser 2-3 questions ouvertes pour comprendre les grandes composantes :

> "Quelles sont les grandes parties de ce projet selon toi ?"
> "Qu'est-ce qui doit absolument être en place pour que ça fonctionne ?"
> "Quels sont les éléments les plus incertains ou risqués ?"

### 2.2 Arbre de branches

Après les réponses, dessiner l'arbre de branches avec les statuts :

```
Projet : [Nom]
├── [ ] Branche A — [description courte]
├── [ ] Branche B — [description courte]
├── [ ] Branche C — [description courte]
└── [ ] Branche D — [description courte]
```

Statuts possibles :
- `[ ]` — non explorée
- `[~]` — en cours d'exploration
- `[✓]` — résolue (clarté suffisante)
- `[!]` — non résolue (bloqueur identifié)
- `[pause]` — mise en pause intentionnelle

### 2.3 Gate Phase 2

L'utilisateur valide l'arbre. Minimum 2 branches requises avant de continuer.

---

## Phase 3 — Exploration (branche par branche)

Explorer chaque branche `[ ]` une par une, dans l'ordre de priorité.

### Format par tour

Chaque tour de Phase 3 suit ce format interne (ne pas tout afficher d'un coup) :

1. **Ciblage interne** (non affiché) — identifier l'axe de scoring le plus bas
   et comprendre pourquoi c'est le goulot d'étranglement pour cette branche.
2. **Question nue** — une seule question, formulée simplement, puis attendre.
3. **Réaction** — après la réponse : avis franc, patterns BAD/GOOD si applicable,
   signaler les red flags.
4. **Scoring visible** — afficher après chaque réponse significative :
   `Objectif X/5 (=) | Comment X/5 (+1: raison) | Critères X/5 (-1: raison)`

### Scoring de clarté — 3 axes

#### Axe Objectif (la destination)

| Palier | Critère factuel |
|--------|----------------|
| 0 | Pas encore discuté |
| 1 | Aucun qui/quoi/pourquoi identifiable |
| 2 | Qui OU quoi identifié, pas les deux |
| 3 | Qui + quoi + pourquoi identifiés |
| 4 | Au moins 2 métriques chiffrées |
| 5 | Métriques testées sur de vrais utilisateurs |

#### Axe Comment (le chemin)

| Palier | Critère factuel |
|--------|----------------|
| 0 | Pas encore discuté |
| 1 | Aucune étape concrète |
| 2 | Étapes nommées sans dates ni responsables |
| 3 | Étapes + responsables OU dates |
| 4 | Étapes + responsables + dates + budget |
| 5 | Preuves d'exécution (artefacts, commits, livrables) |

#### Axe Critères (la réussite)

| Palier | Critère factuel |
|--------|----------------|
| 0 | Pas encore discuté |
| 1 | Aucun critère mesurable |
| 2 | Critère nommé mais non mesurable |
| 3 | Au moins 1 critère mesurable |
| 4 | Au moins 2 critères mesurables avec seuils |
| 5 | Critères mesurés sur données réelles |

#### Règles de ciblage et de mouvement

- **Ciblage :** poser la prochaine question sur l'axe le plus bas.
  En cas d'égalité : Critères > Objectif > Comment.
- **Montée :** uniquement sur preuve factuelle (chiffre, nom, exemple concret,
  date réelle).
- **Baisse :** sur contradiction détectée, invalidation d'une hypothèse, ou
  imprécision confirmée.
- **Baisse forcée de 2+** si une prémisse invalidée en Phase 4 impacte
  une branche complète.

### Anti-complaisance

**Jamais** : "c'est intéressant", "bonne réponse", "excellent", "parfait",
"super idée". Ces formules signalent une complaisance qui nuit à la qualité.

Utiliser des patterns BAD/GOOD contrastifs :

**Exemple 1 — Marché non validé**

BAD (complaisant) :
> "Super, tu as identifié un marché potentiel !"

GOOD (franc) :
> "Tu as un intuition de marché, mais aucune donnée réelle. Combien de
> personnes t'ont dit qu'elles paieraient pour ça — avec un montant précis ?"

**Exemple 2 — Planning optimiste**

BAD (complaisant) :
> "Ton planning semble ambitieux mais faisable."

GOOD (franc) :
> "6 semaines pour ça avec une équipe de 2, sans budget marketing ? Quel est
> le risque numéro 1 qui ferait glisser cette date ?"

**Exemple 3 — Critère flou**

BAD (complaisant) :
> "Les utilisateurs vont adorer ça."

GOOD (franc) :
> "'Les utilisateurs adorent' n'est pas mesurable. Quel comportement concret
> prouverait que c'est un succès — un taux, une fréquence, un montant ?"

### Push twice

La première réponse aux questions difficiles est souvent la version polie ou
de surface. Pousser une deuxième fois sur les forcing questions :

> "Tu m'as donné la version optimiste. Si tu devais parier ton propre argent
> là-dessus, tu dirais quoi ?"

Jamais plus de 2 relances sur la même question. Passer à la suivante après.

**Exception :** les forcing questions (voir ci-dessous) ne sont jamais skippées,
même si la première réponse semble bonne.

### Routage par question

Étiqueter chaque question (pour usage interne) :

| Tag | Signification | Comportement |
|-----|--------------|-------------|
| `[fait-auto]` | Fait avéré, l'agent peut valider seul | Valider sans relance |
| `[fait-confirm]` | Fait avéré mais besoin de confirmation utilisateur | Confirmer avant de valider |
| `[décision]` | Choix à faire par l'utilisateur | Présenter les options, attendre |
| `[recherche]` | Information externe nécessaire | Déclencher Phase 3.7 si pertinent |

### Smart-skip

Si une réponse contient les 3 éléments suivants, passer à la question suivante
sans relance :
1. Un **chiffre** (quantité, date, pourcentage, montant)
2. Un **nom propre** (personne, outil, entreprise, lieu)
3. Un **exemple concret** (cas réel, expérience passée, prototype existant)

**Exception :** les forcing questions ne sont jamais skippées, même avec les
3 éléments présents.

### Forcing questions par domaine

Ces questions sont obligatoires selon le type détecté en Phase 1 :

**business/startup**
- "Combien de personnes t'ont dit qu'elles paieraient — avec un montant précis ?"
- "Quel est ton avantage défendable dans 2 ans si un concurrent bien financé
  copie ton idée demain ?"

**produit/app**
- "Décris le workflow complet d'un utilisateur de son premier clic jusqu'à
  la valeur qu'il reçoit."
- "Qu'est-ce qui existe déjà qui ressemble à ça, et pourquoi les gens
  ne l'utilisent pas ?"

**événement/projet-perso**
- "Quel est le scénario exact le jour J si le prestataire principal annule
  à 24h ?"
- "Qui prend les décisions si tu es indisponible ?"

**carrière/formation**
- "Dans 6 mois, comment sais-tu que tu as progressé — avec un indicateur
  externe, pas ton propre ressenti ?"
- "Qu'est-ce qui t'a empêché d'avancer sur ce sujet jusqu'ici ?"

**créatif/contenu**
- "Qui est le lecteur/spectateur idéal — décris une personne réelle que
  tu connais."
- "Quel contenu similaire existe, et qu'est-ce que le tien apporte en plus ?"

**communauté/open-source**
- "Quel problème résout ce projet pour les contributeurs, pas seulement
  pour les utilisateurs ?"
- "Comment les décisions seront-elles prises quand tu ne seras plus là ?"

**infrastructure/ops**
- "Quel est le scénario d'échec le plus coûteux, et quel est le RTO/RPO
  acceptable ?"
- "Comment détectes-tu une régression en production avant que les utilisateurs
  ne la signalent ?"

**juridique/compliance**
- "Quel est le risque résiduel après toutes les mesures de conformité en place ?"
- "Qui est responsable légalement si un problème survient ?"

### Registre de concepts

Maintenir un registre interne des termes importants rencontrés pendant l'entretien :

```
Registre de concepts :
- [terme] : [définition donnée par l'utilisateur]
- [terme] : [définition donnée par l'utilisateur]
```

Si l'utilisateur utilise un terme défini différemment plus tard → signaler la
contradiction immédiatement :

> "Attends — tu avais défini [terme] comme [définition initiale], mais là tu
> sembles dire [définition contradictoire]. Laquelle est correcte ?"

Afficher un résumé de la branche après chaque branche complétée :

```
Branche [Nom] [✓]
- Résumé : [2-3 phrases]
- Score : Objectif X/5 | Comment X/5 | Critères X/5
```

Puis mettre à jour l'arbre de branches avec le nouveau statut.

Afficher la progression après chaque branche :
`X/Y branches — Scoring : Objectif X/5 | Comment X/5 | Critères X/5`

### Phase 3.5 — Changement de perspective (conditionnel)

**Déclencher sur signal** (l'un ou plusieurs de) :
- Blocage sur la même question depuis 3+ tours
- Complexité galopante : chaque réponse ouvre 2 nouvelles questions
- Tout semble trop facile : aucune résistance, aucun risque identifié

**Modes disponibles** (choisir le plus adapté) :

| Mode | Ce qu'il fait |
|------|--------------|
| Contrarian | Chercher activement pourquoi ça va échouer |
| Simplificateur | Identifier ce qu'on peut couper sans perdre la valeur |
| Recentreur | Revenir à la question fondamentale du projet |
| Utilisateur Final | Se mettre dans la peau de l'utilisateur le plus improbable |
| Concurrent | Analyser ce qu'un concurrent ferait différemment |

Annoncer le changement de perspective avant de l'appliquer :

> "Je vais changer d'angle pour t'aider à voir quelque chose qu'on a
> peut-être manqué. Mode [Nom] : [question depuis ce nouveau point de vue]."

### Phase 3.7 — Recherche web (conditionnel)

**Déclencher sur signal** (l'un ou plusieurs de) :
- Un chiffre clé est avancé sans source ("le marché fait 10 milliards")
- Un concurrent est mentionné sans analyse réelle
- Une faisabilité technique est affirmée sans validation

**Processus en 3 couches :**

1. **Couche 1 — Validation des faits** : vérifier le chiffre ou l'affirmation
   avec une recherche web ciblée.
2. **Couche 2 — Contexte concurrentiel** : identifier 2-3 acteurs similaires
   et leur positionnement.
3. **Couche 3 — Signal d'alerte ou eureka** : conclure avec l'une de ces deux
   formules :
   - Signal d'alerte : "Les données suggèrent que [conclusion]. Ça change-t-il
     quelque chose à ton approche ?"
   - Eureka : "J'ai trouvé un angle que tu n'avais pas mentionné : [insight].
     Est-ce que ça ouvre des possibilités ?"

### Gate Phase 3

Aucune branche ne doit rester avec le statut `[ ]` (non explorée) ou `[~]`
(en cours) dans le registre avant de passer à la Phase 4.

---

## Phase 4 — Challenge

### 4.1 Hypothèses cachées

Lister les hypothèses implicites du projet dans ces catégories :

```
Hypothèses cachées identifiées :
- Marché : [ex: "les utilisateurs changeront leur comportement actuel"]
- Ressources : [ex: "une personne suffit pour livrer en 3 mois"]
- Comportements : [ex: "les clients paieront sans essai gratuit"]
- Technique : [ex: "l'API tierce sera stable et disponible"]
- Timing : [ex: "le marché sera prêt dans 6 mois"]
```

Demander à l'utilisateur de valider ou invalider chaque hypothèse.

### 4.2 Pre-mortem obligatoire

Toujours poser cette question, sans exception :

> "Imaginons que nous sommes dans 1 an et que le projet a échoué.
> Personne n'en parle, l'équipe s'est dispersée, les objectifs n'ont pas
> été atteints. Qu'est-ce qui s'est passé ?"

Documenter le scénario d'échec principal pour le champ `premortem` du spec.yaml.

### Phase 4.5 — Deuxième opinion (sous-agent)

Spawner un sous-agent avec le contexte complet de l'entretien et lui demander
de répondre à ces 4 questions — sans complaisance :

1. "Quel est l'élément le plus solide de ce projet ?"
2. "Quel est l'élément le plus risqué ou le moins validé ?"
3. "Quel angle mort n'a pas été adressé dans la conversation ?"
4. "Quel est le test faisable en 48h qui validerait ou invaliderait
   l'hypothèse centrale ?"

Présenter les réponses à l'utilisateur et discuter les points 2, 3, et 4.

### 4.3 Retour en Phase 3 (conditionnel)

Si un axe de scoring tombe sous 4/5 suite au Challenge → retourner en Phase 3
sur les branches impactées avant de continuer.

### Gate Phase 4

Score total >= 12/15 ET chaque axe >= 4/5 requis pour passer en Phase 5.

Si le gate n'est pas atteint → identifier les axes bloquants et retourner en
Phase 3 sur les branches correspondantes.

**Note :** ce gate est vérifié par l'agent, pas par le CLI. Le CLI ne vérifie que le gate d'ambiguïté (0.2). La rigueur du mode deep repose sur la discipline de l'agent à respecter ces phases.

---

## Phase 5 — Extraction → spec.yaml

### Checklist de fin

Toutes les cases suivantes doivent être cochées avant d'appeler le CLI :

- [ ] Branches : toutes `[✓]` ou `[!]` dans le registre
- [ ] Hypothèses : listées et validées/invalidées par l'utilisateur
- [ ] Pre-mortem : scénario d'échec discuté et documenté
- [ ] Challenge : au moins un pattern BAD/GOOD utilisé OU un changement
      de perspective déclenché pendant l'entretien
- [ ] Clarté : total >= 12/15 ET chaque axe >= 4/5
- [ ] Actions : prochaines étapes identifiées avec l'utilisateur

### Mapping entretien → spec.yaml

| Donnée collectée | Champ spec.yaml |
|------------------|----------------|
| Vision synthétisée + résumés de branches | `goal` |
| Invariants identifiés + hypothèses validées | `constraints` |
| Critères mesurables (palier 4+ du scoring) | `success_criteria` |
| Contexte existant (brownfield) | `context` |
| Score de clarté 3 axes | `clarity_score` |
| Risques identifiés pendant l'entretien | `risks` |
| Hypothèses validées/invalidées | `assumptions` |
| Scénario d'échec du pre-mortem | `premortem` |
| Nombre de branches explorées | `branches_explored` |
| Termes clés + définitions du registre | `concepts` |
| Valeur fixe `"deep"` | `interview_mode` |

### Écriture des métadonnées deep

**Étape 1 — Écrire `deep-meta.json`**

Utiliser le `Write` tool pour créer le fichier JSON dans le répertoire courant :

```json
{
  "interview_mode": "deep",
  "clarity_score": {
    "objectif": <int 0-5>,
    "comment": <int 0-5>,
    "criteres": <int 0-5>,
    "total": <int 0-15>
  },
  "risks": [
    {"description": "<risque>", "severity": "<low|medium|high>"}
  ],
  "assumptions": [
    {"statement": "<hypothèse>", "status": "<validated|invalidated|uncertain>"}
  ],
  "premortem": "<scénario d'échec en 1-3 phrases>",
  "branches_explored": <int>,
  "concepts": [
    {"term": "<terme>", "definition": "<définition>"}
  ]
}
```

**Étape 2 — Appeler le CLI**

```text
Bash('mobius interview --non-interactive \
  --template <web|cli|lib|etl|mobile|docs|blank> \
  --project-type <greenfield|brownfield> \
  --goal "<vision synthétisée>" \
  --constraint "<invariant 1>" \
  --constraint "<invariant 2>" \
  --success-criterion "<critère mesurable 1>" \
  --success-criterion "<critère mesurable 2>" \
  [--context "<contexte brownfield>"] \
  --deep-metadata /absolute/path/to/deep-meta.json \
  --output spec.yaml')
```

Utiliser le chemin absolu retourné par le Write tool pour `deep-meta.json`.

Passer chaque contrainte et chaque critère comme son propre flag.
Citer toutes les valeurs qui contiennent des espaces.

**Étape 3 — Gate d'ambiguïté**

Le gate Python (`compute_ambiguity_score`, seuil 0.2) reste actif. Il ne
devrait jamais échouer après un deep interview correct (scoring >= 12/15).
Si malgré tout le gate échoue :

1. Afficher l'erreur retournée par le CLI.
2. Identifier les champs problématiques (`goal`, `constraints`, ou
   `success_criteria`).
3. Proposer des reformulations précises à l'utilisateur.
4. Réessayer avec les champs corrigés.

**Étape 4 — Présenter les résultats et proposer les actions suivantes**

Afficher le chemin vers `spec.yaml` et proposer :

```text
Bash('mobius seed spec.yaml')
Bash('mobius run --spec spec.yaml')
Bash('mobius status <run_id> --follow')
```

---

## Règles du mode deep

1. **Une question à la fois.** Poser une question, attendre la réponse, puis
   continuer. Ne jamais poser plusieurs questions dans le même message.

2. **Français par défaut.** Termes techniques anglais courants gardés tels
   quels (spec, roadmap, brownfield, greenfield, etc.).

3. **Jamais de MCP.** Mobius est un CLI. Toujours utiliser le `Bash` tool.

4. **Sortie anticipée.** Si l'utilisateur dit "assez", "stop", "on passe",
   ou "extrait quand même" :
   - Afficher la checklist avec les cases cochées et non cochées.
   - Marquer le spec comme INCOMPLET dans le résumé.
   - Si l'utilisateur insiste → synthèse immédiate et extraction partielle
     avec les données disponibles. Signaler les champs manquants dans le YAML.

5. **Progression affichée.** Après chaque branche complétée, afficher :
   `X/Y branches — Scoring : Objectif X/5 | Comment X/5 | Critères X/5`

6. **Anti-complaisance stricte.** Jamais de validation automatique. Chaque
   avancement de score doit être justifié par une preuve factuelle.

---

## What NOT to do

- Do **not** call any MCP tool. Mobius is a plain CLI.
- Do **not** pass a flat `--constraint "a, b, c"` — repeat the flag for each.
- Do **not** invent a fixture YAML file unless the user explicitly asks for
  one — `--goal/--constraint/--success-criterion` is the default agent path.
- Do **not** skip the conversation and go straight to invoking the CLI; the
  whole point of both modes is eliciting the spec from the user.
- Do **not** use phrases like "c'est intéressant", "bonne réponse", "excellent",
  or "parfait" — these signal complacency and undermine the interview quality.
- Do **not** ask multiple questions in a single message in deep mode.
- Do **not** mark a branch `[✓]` without factual evidence (a number, a name,
  a concrete example) supporting clarity at palier 3 or above on all 3 axes.
- Do **not** skip the pre-mortem — it is mandatory in every deep interview.
- Do **not** write `deep-meta.json` with missing required fields — the CLI
  will reject it with an error.
