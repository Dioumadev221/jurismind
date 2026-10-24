"""La démonstration publique : un cabinet simulé, en ligne, sans modèle sur le serveur.

Trois temps, dans cet ordre :

1. **enregistrer** — sur une machine qui fait tourner les modèles, un scénario passe par
   l'API exactement comme un visiteur le ferait, et chaque appel aux modèles est consigné
   (`jurismind.llm.rejeu`). Le scénario retenu est écrit dans `demo/scenario.json` :
   c'est ce que l'interface proposera aux visiteurs.
2. **exporter** — la base, indexée et enrichie par le scénario, est figée dans
   `demo/base.sql.gz`, avec l'état du CRM simulé (`demo/crm.json`).
3. **restaurer** — au démarrage du serveur public, une base vide reçoit cet export ; une
   base déjà chargée est seulement remise dans l'état de l'export, pour que les décisions
   prises par un visiteur ne s'imposent pas au suivant.
"""

from pathlib import Path

# Hors de `data/`, que Git et Docker ignorent : ces fichiers sont versionnés et livrés
# dans l'image, puisque le serveur public n'a rien d'autre pour exister.
DOSSIER_DEMO = Path("demo")
SCENARIO = DOSSIER_DEMO / "scenario.json"
EXPORT = DOSSIER_DEMO / "base.sql.gz"
ENREGISTREMENTS = DOSSIER_DEMO / "enregistrements.jsonl"
CRM = DOSSIER_DEMO / "crm.json"
