# Issue tracker: Local Markdown

Issues et PRD pour ce repo vivent comme des fichiers markdown dans `.scratch/`.

## Conventions

- Une feature par dossier : `.scratch/<feature-slug>/`
- Le PRD est `.scratch/<feature-slug>/PRD.md`
- Les issues d'implémentation sont `.scratch/<feature-slug>/issues/<NN>-<slug>.md`, numérotées à partir de `01`
- L'état de triage est consigné en haut du fichier sous forme de ligne `Status:` (voir `triage-labels.md` pour les valeurs)
- Les commentaires et l'historique de discussion s'ajoutent au bas du fichier sous une rubrique `## Comments`

## Quand une skill dit « publier dans l'issue tracker »

Crée un nouveau fichier sous `.scratch/<feature-slug>/` (en créant le dossier si nécessaire).

## Quand une skill dit « récupérer le ticket pertinent »

Lis le fichier au chemin référencé. L'utilisateur passera normalement le chemin ou le numéro d'issue directement.
