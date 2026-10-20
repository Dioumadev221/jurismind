#!/usr/bin/env bash
# Amorçage de la démonstration : du conteneur vide au cabinet consultable.
#
# Exécuté une seule fois. Un témoin dans le volume de données évite de tout régénérer à
# chaque `docker compose up` — la génération du corpus et le calcul des vecteurs coûtent
# plusieurs minutes sur un processeur, et les refaire effacerait le travail déjà indexé.
# `docker compose down -v` supprime le volume, donc le témoin : c'est la façon de repartir
# de zéro, et elle est explicite.
#
# Chaque étape échoue bruyamment (`set -e`) : une amorce à moitié faite donnerait une
# interface qui s'ouvre sur un cabinet vide, ce qui est pire qu'une erreur au démarrage.

set -euo pipefail

TEMOIN="/app/data/.amorce-faite"
TAILLE="${DEMO_TAILLE:-small}"
GRAINE="${DEMO_GRAINE:-42}"

if [ -f "$TEMOIN" ]; then
    echo "Amorce déjà faite le $(cat "$TEMOIN"). Rien à refaire."
    echo "Pour repartir de zéro : docker compose down -v"
    exit 0
fi

attendre() {
    local nom="$1" commande="$2" essais="${3:-60}"
    echo -n "Attente de $nom "
    for _ in $(seq "$essais"); do
        if eval "$commande" >/dev/null 2>&1; then
            echo " prêt."
            return 0
        fi
        echo -n "."
        sleep 2
    done
    echo " ABANDON : $nom n'a pas répondu."
    return 1
}

attendre "PostgreSQL" "python -c \"
import os, psycopg
psycopg.connect(
    host=os.environ.get('POSTGRES_HOST', 'postgres'),
    port=os.environ.get('POSTGRES_PORT', '5432'),
    user=os.environ['POSTGRES_USER'],
    password=os.environ['POSTGRES_PASSWORD'],
    dbname=os.environ['POSTGRES_DB'],
).close()\""

echo
echo "── 1/6  Cabinet simulé ($TAILLE, graine $GRAINE) ───────────────────────────────"
# Produit la base « existante » du cabinet, les fiches du CRM et les pièces (PDF, DOCX,
# scans). C'est le point de départ : JurisMind ne crée jamais de données métier, il lit
# celles qui existent déjà.
python -m simulation --taille "$TAILLE" --seed "$GRAINE"

echo
echo "── 2/6  Schéma JurisMind ───────────────────────────────────────────────────────"
# Les migrations portent aussi les règles d'isolation PostgreSQL (Row-Level Security),
# écrites à la main : ce n'est pas que de la structure, c'est la sécurité du produit.
alembic upgrade head

echo
echo "── 3/6  Connecteurs (base existante + CRM) ─────────────────────────────────────"
# Toutes les routes métier du CRM exigent une clé ; `/openapi.json` est servi sans jeton et
# prouve que l'application est montée, pas seulement que le port écoute.
attendre "le CRM simulé" "curl -fsS ${CRM_BASE_URL:-http://crm:8100}/openapi.json"
python -m jurismind.connectors

echo
echo "── 4/6  Lecture des pièces, OCR et vecteurs ────────────────────────────────────"
attendre "Ollama" "curl -fsS ${OLLAMA_BASE_URL:-http://ollama:11434}/api/tags"
python -m jurismind.ingestion

echo
echo "── 5/6  Valeurs des actes des dossiers ouverts ─────────────────────────────────"
# Montants, dates et délais lus dans chaque acte : c'est ce que l'échéancier et les points
# d'attention comptent. Seuls les dossiers ouverts sont traités — ce sont les seuls dont
# les délais courent encore. Les autres se traitent plus tard, à la demande :
#     docker compose exec api python -m jurismind.extraction --limite 0
python -m jurismind.extraction --en-cours --limite 0

echo
echo "── 6/6  Comptes de démonstration ───────────────────────────────────────────────"
# Les mots de passe sont écrits dans data/comptes-demo.txt, à l'intérieur du volume :
# jamais dans l'image, jamais dans le dépôt, jamais dans les journaux.
python -m jurismind.api.comptes --demo

date -u +"%Y-%m-%dT%H:%M:%SZ" > "$TEMOIN"
echo
echo "════════════════════════════════════════════════════════════════════════════════"
echo " Cabinet prêt.  Interface : http://localhost:8000/app"
echo "                API       : http://localhost:8000/docs"
echo " Identifiants  : docker compose exec api cat data/comptes-demo.txt"
echo "════════════════════════════════════════════════════════════════════════════════"
