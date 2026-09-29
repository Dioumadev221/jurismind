"""Récupère les données de langue de Tesseract nécessaires à l'OCR.

Le pack français n'est pas toujours installé avec Tesseract, et le fichier ne doit pas être
versionné (1,1 Mo de données binaires). Cette commande le télécharge dans le dossier indiqué
par `TESSDATA_DIR`, sans droits administrateur.

Usage : uv run python -m jurismind.ingestion.langues
"""

import sys
from pathlib import Path

import httpx

from jurismind.core.config import get_settings

SOURCE = "https://github.com/tesseract-ocr/tessdata_fast/raw/main/{langue}.traineddata"
LANGUES = ("fra",)


def telecharger(langue: str, dossier: Path) -> Path:
    fichier = dossier / f"{langue}.traineddata"
    if fichier.exists():
        print(f"{fichier} : déjà présent")
        return fichier
    dossier.mkdir(parents=True, exist_ok=True)
    url = SOURCE.format(langue=langue)
    print(f"téléchargement de {url}")
    reponse = httpx.get(url, follow_redirects=True, timeout=60)
    reponse.raise_for_status()
    fichier.write_bytes(reponse.content)
    print(f"{fichier} : {len(reponse.content) // 1024} Ko")
    return fichier


def main() -> int:
    dossier = get_settings().tessdata_dir
    if not dossier:
        print("TESSDATA_DIR n'est pas défini : les langues doivent être installées avec Tesseract.")
        return 1
    for langue in LANGUES:
        telecharger(langue, Path(dossier))
    return 0


if __name__ == "__main__":
    sys.exit(main())
