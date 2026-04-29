# Triage Labels

Les skills parlent en termes de cinq rôles canoniques de triage. Ce fichier mappe ces rôles aux chaînes de labels effectivement utilisées dans le tracker de ce repo.

| Label dans mattpocock/skills | Label dans notre tracker | Signification                                         |
| ---------------------------- | ------------------------ | ----------------------------------------------------- |
| `needs-triage`               | `needs-triage`           | Le mainteneur doit évaluer cette issue                |
| `needs-info`                 | `needs-info`             | En attente d'informations supplémentaires du reporter |
| `ready-for-agent`            | `ready-for-agent`        | Entièrement spécifié, prêt pour un agent AFK          |
| `ready-for-human`            | `ready-for-human`        | Nécessite une implémentation humaine                  |
| `wontfix`                    | `wontfix`                | Ne sera pas traité                                    |

Quand une skill mentionne un rôle (par exemple « applique le label de triage AFK-ready »), utilise la chaîne de label correspondante de ce tableau.

Les issues vivent comme fichiers markdown sous `.scratch/<feature>/issues/` (voir `issue-tracker.md`). Le label de triage est consigné en haut du fichier sur une ligne `Status:`, par exemple :

```markdown
Status: ready-for-agent
```

Modifie la colonne de droite si tu veux faire évoluer ce vocabulaire plus tard.
