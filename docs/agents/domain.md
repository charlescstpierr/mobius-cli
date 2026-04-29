# Domain Docs

Comment les skills d'ingénierie doivent consommer la documentation domaine de ce repo lorsqu'elles explorent la base de code.

## Avant d'explorer, lire ceci

- **`CONTEXT.md`** à la racine du repo
- **`docs/adr/`** — lire les ADRs qui touchent à la zone sur laquelle tu vas travailler

Si l'un de ces fichiers n'existe pas, **procède silencieusement**. Ne signale pas leur absence ; ne propose pas de les créer en amont. La skill productrice (`/grill-with-docs`) les crée paresseusement quand des termes ou décisions sont effectivement résolus.

## Structure de fichiers

Repo single-context (ce repo) :

```
/
├── CONTEXT.md
├── docs/adr/
│   ├── 0001-...md
│   └── 0002-...md
└── src/
```

## Utilise le vocabulaire du glossaire

Quand ta sortie nomme un concept domaine (dans un titre d'issue, une proposition de refactor, une hypothèse, un nom de test), utilise le terme tel que défini dans `CONTEXT.md`. Ne dérive pas vers des synonymes que le glossaire évite explicitement.

Si le concept dont tu as besoin n'est pas encore dans le glossaire, c'est un signal — soit tu inventes du langage que le projet n'utilise pas (reconsidère), soit il y a un vrai vide (note-le pour `/grill-with-docs`).

## Signale les conflits avec les ADR

Si ta sortie contredit un ADR existant, surface-le explicitement plutôt que de l'écraser silencieusement :

> _Contredit ADR-0007 (...) — mais vaut la peine d'être rouvert parce que…_
