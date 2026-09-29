"""Outils de texte partagés par la recherche et par la vérification des réponses."""

import re
import unicodedata

# Références que l'on retrouve littéralement dans les pièces du cabinet :
# factures (FA-2025-978), RCCM (SN-DKR-2019-B-62433), ordonnances et rôles (1703/2022).
REFERENCES = re.compile(r"\b(?:[A-Z]{2,4}-[\w-]*\d[\w-]*|\d{2,5}/\d{4})\b")


def normaliser(texte: str) -> str:
    """Forme comparable : sans accents, sans ponctuation, en minuscules."""
    sans_accent = unicodedata.normalize("NFKD", texte).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", " ", sans_accent.lower()).strip()


def references_brutes(texte: str) -> list[str]:
    """Références telles qu'écrites, pour une recherche exacte en base."""
    return REFERENCES.findall(texte)


def references_de(texte: str) -> set[str]:
    """Références sous forme comparable, pour vérifier qu'une source les contient."""
    return {normaliser(reference) for reference in REFERENCES.findall(texte)}
