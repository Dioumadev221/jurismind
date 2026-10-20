# Préparer la démonstration publique depuis la pile Docker, sans Python sur la machine.
#
#   docker compose up -d --build      # la pile complète, amorcée (premier démarrage : 30 à 60 min)
#   .\docker\enregistrer-demo.ps1
#
# Tout s'exécute dans les conteneurs : le scénario passe par l'API avec les vrais modèles,
# la base est figée par le pg_dump du conteneur PostgreSQL (même version que le serveur).
# Les fichiers arrivent dans demo/, prêts à être versionnés. Voir docs/DEPLOY_FR.md.

$ErrorActionPreference = "Stop"
Set-Location (Split-Path $PSScriptRoot -Parent)

function Executer {
    & docker compose @args
    if ($LASTEXITCODE -ne 0) { throw "Échec : docker compose $args" }
}

Write-Host "1/4  Champs clés des dossiers en cours (ignoré s'ils sont déjà extraits)"
Executer exec api python -m jurismind.extraction --en-cours --limite 0

Write-Host "2/4  Scénario joué avec les vrais modèles (quelques dizaines de minutes sur processeur)"
Executer exec api python -m jurismind.demo enregistrer

Write-Host "3/4  Base figée"
Executer exec postgres sh -c "pg_dump -U jurismind --no-owner --no-privileges --exclude-schema demo_origine jurismind | gzip -9 > /tmp/base.sql.gz"

Write-Host "4/4  Fichiers copiés dans demo/"
New-Item -ItemType Directory -Force demo | Out-Null
Executer cp postgres:/tmp/base.sql.gz demo/base.sql.gz
Executer cp api:/app/demo/scenario.json demo/scenario.json
Executer cp api:/app/demo/enregistrements.jsonl demo/enregistrements.jsonl
Executer cp api:/app/data/crm/crm.json demo/crm.json

Get-ChildItem demo | Format-Table Name, Length
Write-Host "Terminé. Vérifier le bilan dans demo/scenario.json, puis : git add demo; git commit; git push"
