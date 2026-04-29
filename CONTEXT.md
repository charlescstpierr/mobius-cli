# Mobius

Mobius est un *acceptance-criteria event tracker* : un CLI Python rapide, sans MCP ni LLM, qui enregistre l'évolution d'un projet décrit par un `spec.yaml` comme une suite d'événements rejouables. Mobius ne lance jamais de commandes — il observe.

## Language

**Spec**:
Le fichier `spec.yaml` qui décrit l'intention d'un projet (`goal`, `constraints`, `success_criteria`, `steps`, `matrix`). Source de vérité versionnée par l'utilisateur.
_Avoid_: config, manifest, plan

**Session**:
L'identité narrative d'une *Spec* à travers le temps, portée par le `session_id` inscrit dans le YAML. Une *Session* survit à plusieurs *Runs* successifs ; elle change uniquement quand `mobius evolve` produit une nouvelle génération de la spec (la nouvelle *Session* est reliée à l'ancienne par *Lineage*).
_Avoid_: workspace, project id

**Run**:
Une fenêtre de tracking ouverte par `mobius run --spec <spec>`, identifiée par un `run_id`, qui collecte les *Events* liés à une *Spec* jusqu'à clôture. Mobius n'exécute aucun *Step*.
_Avoid_: execution, job, build

**Event**:
Un message typé d'une **grammaire fermée et versionnée** (par exemple `RunOpened`, `StatusReported`, `QaFinding`, `EvolvedFrom`, `RunClosed`), persisté dans l'*Event store*. Toutes les sorties dérivées (`status`, `qa`, `lineage`) sont des **projections** sur ce flux ; aucun payload libre n'est accepté.
_Avoid_: log entry, message, record

**Event store**:
Le SQLite à `$MOBIUS_HOME/events.db` qui contient l'historique append-only des *Events*. Source unique de vérité opérationnelle ; rejouable ; partitionnable par projet via `MOBIUS_HOME`.
_Avoid_: database, log, journal

**Constraint**:
Un **invariant** qui doit être vrai à **tout instant** pendant la vie d'une *Session*. Sa violation est un échec immédiat détectable par `qa`. Exemples : « API publique stable », « Python ≥3.12 », « pas de MCP ».
_Avoid_: requirement, rule, guideline

**Success criterion**:
Une **assertion binaire évaluée à la fin d'un Run** (ou d'une Session) — pas en cours de route. Exemples : « smoke test passe », « coverage ≥95% sur la révision finale ». Un *Success criterion* peut être satisfait, en échec, ou non vérifié.
_Avoid_: acceptance criterion, goal, target

**Step**:
Un **work item nommé** dans la *Spec* (avec `command` et `depends_on` optionnels), qui sert d'unité de progression rapportée via les *Events* `StatusReported`. Mobius **n'exécute jamais** le `command` d'un *Step* ; c'est une métadonnée pour l'agent ou la CI.
_Avoid_: task, action, command (le mot « command » désigne un champ de Step, pas le Step lui-même)

**Status**:
Projection sur les *Events* d'un *Run* qui répond à **« où en est-on ? »** — état du *Run* (open / closed / expired) + progression de chaque *Step* (todo / in-progress / done / blocked). Exposée par `mobius status <run_id>`.
_Avoid_: progress, state, dashboard

**QA**:
Projection sur les *Events* d'un *Run* qui répond à **« est-ce conforme à la *Spec* ? »** — liste des violations de *Constraints* en cours de *Run*, verdict de chaque *Success criterion* (pass / fail / not-verified), et verdict global. Exposée par `mobius qa <run_id>`.
_Avoid_: test, lint, audit, verdict

**Evolve**:
L'opération qui ferme la *Session* courante et en ouvre une **nouvelle Session descendante**, dont la *Spec* a été révisée par l'agent à la lumière du dernier verdict *QA*. `--generations N` produit une **chaîne linéaire** de N Sessions descendantes (S₁ → S₂ → … → Sₙ). Mobius **enregistre** le diff fourni par l'agent ; il ne le calcule pas.
_Avoid_: regenerate, mutate, fork

**Generation**:
Le rang d'une *Session* dans une chaîne d'*Evolve* (la Session racine est génération 0). Synonyme « propre » de « Session descendante de rang N ».
_Avoid_: iteration, version, revision

**Lineage**:
L'arbre des *Sessions* reliées par les arêtes `EvolvedFrom`. `mobius lineage` matérialise cet arbre — chaque nœud porte ses *Runs* et son verdict *QA*. Le lineage suit les *Sessions*, **pas** les *Runs*.
_Avoid_: history, ancestry, tree

### Scores et gates (v3a)

Trois scores distincts cohabitent ; ils mesurent des choses différentes, à des moments différents, sur des cibles différentes. Ne pas les fusionner sous le mot « score ».

**Ambiguity score**:
Mesure du **flou linguistique d'une *Spec*** au moment de l'*Interview* (composants : `goal`, `constraints`, `success`, `context`). Float 0..1, **plus bas = mieux**. Bloqué par l'*Ambiguity gate* (plafond, défaut 0.2).
_Avoid_: vagueness, fuzziness, score (sans préfixe)

**Maturity score**:
Mesure de la **complétude vérifiable d'une *Spec*** après seed (4 dimensions : criteria_count, verification_ratio, edge_case_ratio, lemmas). Float 0..1, **plus haut = mieux**. Bloqué par la *Maturity gate* (plancher, défaut 0.8). Une spec sous le seuil ne peut pas ouvrir de *Run* sans `--auto-top-up` ou `--force-immature`.
_Avoid_: readiness, completeness, score (sans préfixe)

**Quality score**:
Verdict de **qualité d'un *Run* terminé**, sur 10, agrégé depuis 7 critères mécaniques (couverture, mypy, vérifications, ambigüité résiduelle, ruff…) et 3 critères jugés par LLM (`goal_alignment`, `code_quality`, `test_quality`). **Pas de gate** : c'est un rapport. Accompagné des *Score recommendations*. Le champ JSON s'appelle `score_out_of_10` pour rétrocompat ; le terme canonique en prose est *Quality score*.
_Avoid_: score (sans préfixe), grade, rating

**Score recommendation**:
Une suggestion textuelle attachée à un *Quality score* indiquant comment le Run pourrait gagner des points. Sortie de `v3a/scoring/recommend.py`, listée dans `score_recommendations`.
_Avoid_: hint, advice, todo

**Ambiguity gate** / **Maturity gate**:
Les seuils qui font passer ou bloquer une *Spec* respectivement à l'*Interview* (plafond d'ambiguïté) et à la *Phase* *Maturity* (plancher de maturité). Cas particuliers de *Quality gates*.
_Avoid_: threshold, limit, check

**Quality gates**:
Le terme parapluie pour l'ensemble des seuils v3a qui décident si un *Run* peut transiter d'une *Phase* à la suivante. Inclut au minimum *Ambiguity gate*, *Maturity gate*, et les seuils de couverture / mypy / ruff. Toujours pluriel.
_Avoid_: checks, validators, controls

### Pipeline v3a (`mobius build`)

**Phase**:
Un des **4 stades** du pipeline `mobius build`, dans cet ordre : **Interview → Seed → Maturity → Scoring + Delivery**. Chaque *Phase* est le contexte courant d'un *Run* ; les transitions émettent des *Events* (`PhaseStarted`, `PhaseDone`).
_Avoid_: stage, step (réservé au champ `steps:` de la Spec), milestone

**Auto handoff**:
La transition **automatique** vers la *Phase* suivante quand **toutes les *Quality gates*** de la Phase courante passent. Émet un payload JSON (`AgentPhasePayload`: `phase_done`, `next_phase`, `next_command`) destiné au coding agent, qui décide d'enchaîner ou non. Mobius **propose** la transition ; l'agent l'**effectue**.
_Avoid_: auto-advance, transition, next-step

**Product matrix**:
Le champ `matrix:` de la *Spec* (par exemple `platform: [ios, android]` × `python: [3.12, 3.13]`), interprété comme l'ensemble des **combinaisons** sur lesquelles les *Success criteria* doivent tenir **simultanément**. Le *Quality score* peut être calculé par cellule du *Product matrix* (cf. F10 anti-regression CI).
_Avoid_: variants, environments, axes

## Relationships

- Une **Spec** porte exactement une **Session** active à un instant donné.
- Une **Session** héberge un ou plusieurs **Runs** successifs.
- `mobius evolve` ferme la **Session** courante et en ouvre une nouvelle, reliée à la précédente par **Lineage**.
- Un **Run** émet des **Events** typés dans l'**Event store** ; `status` et `qa` sont des projections sur ce flux.
- Le **Lineage** est un arbre de **Sessions** (pas de Runs) ; chaque arête est un *Evolve*.
- `mobius build` fait passer un **Run** par **4 Phases** (Interview → Seed → Maturity → Scoring + Delivery). Entre deux Phases, l'**Auto handoff** est conditionné par les **Quality gates** : *Ambiguity gate* (avant Seed), *Maturity gate* (avant Scoring), seuils mécaniques (avant Delivery).
- Une **Spec** avec un **Product matrix** non vide est évaluée cellule par cellule ; le **Quality score** peut alors être agrégé (worst cell / moyenne) selon la politique CI.

## Example dialogue

> **Dev:** « J'ai un *Run* qui échoue, le `qa` rapporte un *Constraint* violé. Est-ce que je dois lancer un nouveau *Run* ? »
>
> **Domain expert:** « Pas tout de suite. Un *Constraint* violé veut dire que la *Spec* a été enfreinte **en cours de route** — donc l'agent a fait quelque chose qui contredit un invariant. Regarde d'abord les *Events* de ce *Run* dans l'event store pour voir où la violation est apparue. Si la *Spec* est correcte mais l'agent s'est égaré, ouvre un nouveau *Run* sur la même *Session*. Si la *Spec* elle-même est ambiguë, c'est plutôt `mobius evolve` — ça va clore la *Session* courante et en ouvrir une nouvelle reliée par *Lineage*. »
>
> **Dev:** « Ok. Et le `score_out_of_10` qui est à 6, c'est pareil que la *Maturity gate* qui m'avait bloqué hier ? »
>
> **Domain expert:** « Non, trois choses différentes. La *Maturity gate* (≥ 0.8) c'était sur la *Spec* avant le seed, pour s'assurer qu'elle est assez complète et vérifiable. Le 6/10, c'est le *Quality score* — verdict sur le *Run* terminé, pas sur la *Spec*. Et il y a aussi l'*Ambiguity score* qui mesure le flou linguistique de la *Spec* à l'*Interview*. Trois cibles, trois directions, deux gates. Ne dis jamais juste « le score » dans une PR — précise lequel. »
>
> **Dev:** « Et le `command:` de mon *Step* qui n'a pas tourné ? »
>
> **Domain expert:** « Mobius ne lance jamais le `command` d'un *Step*. C'est de la métadonnée pour ton agent ou ta CI. Mobius enregistre le *StatusReported* que ton agent émet quand il a fini ; il ne déclenche rien lui-même. *Tracker, pas runner.* »

## Flagged ambiguities

- "Run" suggérait une exécution réelle ; clarifié comme **fenêtre de tracking** — Mobius reste *tracker*, jamais *runner*.
- "Session" et "Run" se chevauchaient (deux identifiants distincts dans le système) ; clarifié : *Session* = narrative (durée de vie d'une intention), *Run* = opérationnel (fenêtre d'observation).
- "Constraint" et "Success criterion" se chevauchaient (« coverage ≥95% » pourrait être l'un ou l'autre) ; clarifié par **distinction temporelle** : invariant à tout instant vs assertion à l'arrivée. Une formulation comme « coverage ≥95% » est un *Success criterion* (évalué à la fin) ; « le seuil de couverture ne doit pas régresser » serait un *Constraint*.
- Trois grandeurs s'appelaient toutes « score » (`ambiguity_score`, `MaturityReport.score`, `score_out_of_10`) ; clarifié en **Ambiguity score / Maturity score / Quality score** — cibles, directions et gates distincts. Le mot « score » seul est désormais à éviter en prose.
