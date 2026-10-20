"""Le jour du cabinet.

Toutes les règles qui comptent des jours (délais qui courent, courrier resté sans réponse,
date d'une relance) lisent la date ici plutôt que sur l'horloge. En production c'est la date
réelle ; une démonstration fige celle de son corpus, sans quoi ses délais simulés seraient
tous échus un mois après sa mise en ligne.
"""

from datetime import UTC, date, datetime

from jurismind.core.config import get_settings


def aujourdhui() -> date:
    return get_settings().date_du_cabinet or datetime.now(UTC).date()
