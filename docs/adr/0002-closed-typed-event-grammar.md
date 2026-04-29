# The event store grammar is closed and typed

**Status:** accepted

Tous les *Events* persistés dans `$MOBIUS_HOME/events.db` appartiennent à une **grammaire fermée et versionnée** : une liste finie de types (par exemple `RunOpened`, `StatusReported`, `QaFinding`, `EvolvedFrom`, `PhaseStarted`, `PhaseDone`, `RunClosed`), chacun avec un schéma de payload stable et explicite. L'event store **n'accepte pas** de payload libre ni de type "CustomEvent".

Cette décision a un coût : ajouter une feature qui veut émettre un nouveau type d'event impose d'étendre la grammaire (et de prévoir la rétrocompat des projections sur les events antérieurs). On a accepté ce coût parce que les deux promesses fortes de Mobius — **lineage** et **replay** — exigent une grammaire stable. Avec un journal libre, rejouer un *Run* historique sur une nouvelle version du code casserait dès qu'un payload aurait évolué silencieusement ; les projections (`status`, `qa`, `lineage`) deviendraient du code défensif qui doit gérer du payload inconnu, et le typing strict (mypy `--strict`) perdrait son intérêt.

Conséquence pour les contributeurs : tout nouveau type d'event doit être déclaré dans la grammaire centrale, avec un schéma typé, **avant** d'être émis. Les payloads existants ne se modifient pas en place — on introduit un nouveau type d'event ou on versionne le payload (`v2` etc.). Les outils tiers (agent, CI) qui veulent enregistrer du contexte ad hoc le font dans le champ `metadata` d'un type d'event canonique, jamais dans un type ouvert.
