#!/usr/bin/env bash
# Démarrage de la démonstration publique (Render, ou tout hébergeur d'une image Docker).
#
# Un seul service : l'API, l'interface, la page d'accueil et le CRM simulé, servis par le
# même processus. Pas de modèle : les réponses des modèles sont rejouées depuis
# `demo/enregistrements.jsonl` (voir `jurismind.llm.rejeu`). La base vient de DATABASE_URL :
# vide, elle reçoit l'export `demo/base.sql.gz` ; déjà chargée, elle est remise dans son état
# d'origine, pour que les décisions d'un visiteur ne s'imposent pas au suivant.

set -euo pipefail

PORT="${PORT:-8000}"
# Racine de l'application : /app dans l'image, le dépôt pour un essai hors conteneur.
APP="${APP_DIR:-/app}"
export DEMO=true
export LLM_FOURNISSEUR=demo
export CRM_BASE_URL="${CRM_BASE_URL:-http://127.0.0.1:${PORT}/crm-simule}"
export CRM_DATA_FILE="${CRM_DATA_FILE:-$APP/data/crm/crm.json}"

if [ -z "${DATABASE_URL:-}" ]; then
    echo "DATABASE_URL manquante : la démonstration a besoin d'une base PostgreSQL avec pgvector (Neon, gratuit)."
    exit 1
fi

# Le jour du cabinet : celui de son corpus, tel que le scénario l'a noté.
if [ -z "${DATE_DU_CABINET:-}" ]; then
    DATE_DU_CABINET="$(python -c "import json; print(json.load(open('$APP/demo/scenario.json'))['date_du_cabinet'])")"
    export DATE_DU_CABINET
fi

# Le CRM simulé écrit dans son fichier : on part chaque fois de la copie livrée.
mkdir -p "$(dirname "$CRM_DATA_FILE")"
cp "$APP/demo/crm.json" "$CRM_DATA_FILE"

python -m jurismind.demo preparer

# Un seul processus : le serveur gratuit a 512 Mo, et le CRM simulé garde son état en mémoire.
exec uvicorn jurismind.api.main:app --host 0.0.0.0 --port "$PORT" --workers 1 --proxy-headers --forwarded-allow-ips='*'
