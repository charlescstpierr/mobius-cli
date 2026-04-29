# Mobius is a tracker, not a runner

**Status:** accepted

Mobius enregistre l'évolution d'un projet décrit par un `spec.yaml` mais n'exécute **jamais** les commandes qu'il décrit. La commande `mobius run --spec <spec>` ouvre une fenêtre de tracking (un *Run*) qui collecte des *Events* émis par un coding agent ou par la CI ; le champ `command:` d'un *Step* est de la métadonnée, pas une instruction d'exécution.

Cette décision est volontairement contre-intuitive : un outil qui s'appelle « run » qui ne lance rien va surprendre. On a choisi cette séparation pour garder Mobius **rapide** (pas de runtime long, pas de sandbox), **portable** (n'importe quel runner externe convient : Make, npm, cargo, dbt, fastlane, n'importe quelle CI, n'importe quel agent), et **honnête sur son rôle** (tracker d'acceptance criteria avec lineage et replay first-class). L'alternative — devenir un runner — aurait dupliqué ce que font déjà des dizaines d'outils mieux adaptés et aurait imposé des choix d'environnement à l'utilisateur.

Conséquence pour les contributeurs : aucun code dans `mobius run`, `mobius build` ou ailleurs ne doit invoquer `subprocess`, `os.system`, ou un équivalent **pour exécuter le travail décrit dans la Spec**. Les seuls subprocess autorisés sont les outils de tracking propres à Mobius (par exemple lire la sortie d'un `coverage` qu'**un autre process** a déjà produit).
