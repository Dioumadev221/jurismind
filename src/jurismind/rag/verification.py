"""Vérifications appliquées à une réponse avant de la montrer à un avocat.

Le modèle n'est pas cru sur parole. Trois contrôles, du moins coûteux au plus exigeant :

1. **Aveu d'ignorance** : certaines formulations veulent dire « je n'ai pas trouvé », même
   quand le modèle cite une source au passage.
2. **Cohérence avec la question** : si la question porte sur une référence précise
   (« FA-2023-702 »), la source citée doit contenir cette référence — sinon le modèle a
   répondu à partir d'un autre document.
3. **Citation littérale** : le modèle doit recopier la phrase de la source qui justifie sa
   réponse ; on vérifie qu'elle s'y trouve réellement. C'est ce contrôle qui arrête les
   réponses venues de la culture générale du modèle.
"""

from __future__ import annotations

import logging
import re

from jurismind.core.texte import normaliser, references_de

logger = logging.getLogger(__name__)

# Formulations par lesquelles un modèle annonce qu'il n'a pas trouvé.
AVEUX_D_IGNORANCE = re.compile(
    r"(je ne (trouve|peux|sais) pas"
    r"|n'?(a|ont|est|sont) pas (été )?(abordé|mentionné|traité|précisé|indiqué|répondu|fourni)"
    r"|ne (figure|figurent|permet|permettent|contien\w+) pas"
    r"|(aucune?|pas d[eu']?) (source|information|précision|mention|élément|donnée|taux|indication)"
    r"|il n'y a pas"
    r"|non (mentionné|précisé|indiqué))",
    re.IGNORECASE,
)

# Part des mots de la citation qui doivent se retrouver dans la source (le modèle reformule
# parfois légèrement : on tolère, mais pas une citation inventée).
RECOUVREMENT_MINIMAL = 0.6

# Montants, délais, dates : ce qu'un avocat ne peut pas se permettre de voir inventé.
CHIFFRES = re.compile(r"\d[\d  .,/]*\d|\d")


def avoue_ignorance(texte: str) -> bool:
    return bool(AVEUX_D_IGNORANCE.search(texte))


def references_respectees(question: str, sources: str) -> bool:
    """La référence demandée doit figurer dans les sources citées."""
    attendues = references_de(question)
    if not attendues:
        return True
    presentes = normaliser(sources)
    manquantes = [reference for reference in attendues if reference not in presentes]
    if manquantes:
        logger.info("Références absentes des sources citées : %s", manquantes)
    return not manquantes


def citation_verifiee(citation: str, sources: str) -> bool:
    """La phrase recopiée par le modèle se trouve-t-elle vraiment dans les sources citées ?"""
    extrait = normaliser(citation)
    if len(extrait.split()) < 3:
        return False

    texte = normaliser(sources)
    if extrait in texte:
        return True

    mots = [mot for mot in extrait.split() if len(mot) > 3]
    if not mots:
        return False
    presents = sum(1 for mot in mots if mot in texte)
    recouvrement = presents / len(mots)
    if recouvrement < RECOUVREMENT_MINIMAL:
        logger.info("Citation introuvable dans les sources (%.0f %% des mots)", 100 * recouvrement)
    return recouvrement >= RECOUVREMENT_MINIMAL


def chiffres_de(texte: str) -> list[str]:
    """Montants, délais et dates cités dans un texte, ramenés à leurs seuls chiffres."""
    valeurs = []
    for brut in CHIFFRES.findall(texte):
        chiffres = re.sub(r"[^0-9]", "", brut)
        if chiffres:
            valeurs.append(chiffres)
    return valeurs


def chiffres_ancres(reponse: str, sources: str) -> bool:
    """Tout chiffre affirmé (montant, délai, date) doit figurer dans la source citée.

    C'est le contrôle le plus utile en droit : une reformulation est acceptable, un montant
    inventé ne l'est jamais. Il sert aussi de filet quand la citation littérale a été
    légèrement reformulée par le modèle.
    """
    attendus = chiffres_de(reponse)
    if not attendus:
        return False  # une réponse sans aucun chiffre ne peut pas être ancrée par ce moyen
    presents = " ".join(chiffres_de(sources))
    manquants = [valeur for valeur in attendus if valeur not in presents]
    if manquants:
        logger.info("Chiffres absents des sources citées : %s", manquants)
    return not manquants
