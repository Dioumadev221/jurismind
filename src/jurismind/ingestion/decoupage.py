"""Découpage d'un document en extraits pour la recherche.

Un morceau trop grand dilue le sens et sature le contexte du modèle ; trop petit, il perd
ce qui le rend compréhensible. On vise environ 300 mots, en coupant de préférence entre
deux paragraphes — c'est-à-dire, dans un acte juridique, entre deux articles ou deux
attendus. Un léger chevauchement évite qu'une phrase coupée en deux devienne introuvable.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from jurismind.ingestion.lecture import Lecture, Page

TAILLE_CIBLE = 1100  # caractères, soit environ 300 mots
TAILLE_MAXIMALE = 1600
TAILLE_MINIMALE = 120  # en dessous, on rattache au morceau précédent
CHEVAUCHEMENT = 180

FIN_DE_PHRASE = re.compile(r"(?<=[.!?;:])\s+")


@dataclass
class Morceau:
    """Un extrait prêt à être enregistré : son texte, sa page et son rang dans le document."""

    position: int
    page: int | None
    contenu: str


def _paragraphes(texte: str) -> list[str]:
    morceaux = [
        bloc.strip() for bloc in re.split(r"\n\s*\n|\n(?=\s*(?:Article|ARTICLE|PAR CES MOTIFS))", texte)
    ]
    return [bloc for bloc in morceaux if bloc]


def _couper_long(bloc: str) -> list[str]:
    """Coupe un paragraphe trop long entre deux phrases plutôt qu'au milieu d'un mot."""
    if len(bloc) <= TAILLE_MAXIMALE:
        return [bloc]
    morceaux: list[str] = []
    courant = ""
    for phrase in FIN_DE_PHRASE.split(bloc):
        if courant and len(courant) + len(phrase) + 1 > TAILLE_CIBLE:
            morceaux.append(courant.strip())
            courant = phrase
        else:
            courant = f"{courant} {phrase}".strip()
    if courant.strip():
        morceaux.append(courant.strip())
    return morceaux


def _fin_de(texte: str) -> str:
    """Les dernières phrases d'un morceau, reprises au début du suivant."""
    if len(texte) <= CHEVAUCHEMENT:
        return texte
    queue = texte[-CHEVAUCHEMENT:]
    phrases = FIN_DE_PHRASE.split(queue)
    return " ".join(phrases[1:]).strip() if len(phrases) > 1 else queue.strip()


def decouper_page(page: Page) -> list[str]:
    """Regroupe les paragraphes d'une page en morceaux de taille utile."""
    morceaux: list[str] = []
    courant = ""
    for paragraphe in _paragraphes(page.texte):
        for bloc in _couper_long(paragraphe):
            if courant and len(courant) + len(bloc) + 2 > TAILLE_CIBLE:
                morceaux.append(courant)
                debut = _fin_de(courant)
                courant = f"{debut}\n{bloc}" if debut else bloc
            else:
                courant = f"{courant}\n\n{bloc}".strip()
    if courant.strip():
        morceaux.append(courant.strip())

    # Un dernier morceau minuscule (une signature, une mention) va avec le précédent.
    if len(morceaux) > 1 and len(morceaux[-1]) < TAILLE_MINIMALE:
        dernier = morceaux.pop()
        morceaux[-1] = f"{morceaux[-1]}\n{dernier}"
    return morceaux


def decouper(lecture: Lecture) -> list[Morceau]:
    """Découpe un document lu en extraits numérotés, en gardant la page d'origine."""
    extraits: list[Morceau] = []
    for page in lecture.pages:
        if not page.texte.strip():
            continue
        for contenu in decouper_page(page):
            extraits.append(Morceau(position=len(extraits), page=page.numero, contenu=contenu))
    return extraits


def decouper_texte(texte: str, page: int | None = None) -> list[Morceau]:
    """Même découpage pour un texte sans pages : un email, une note du CRM."""
    contenus = decouper_page(Page(numero=page or 1, texte=texte))
    return [Morceau(position=rang, page=page, contenu=contenu) for rang, contenu in enumerate(contenus)]
