"""Le cinquième contrôle : la source citée **soutient**-elle vraiment la réponse ?

Les quatre contrôles de `verification.py` sont syntaxiques, donc gratuits et sûrs : ils
vérifient qu'une citation existe, qu'elle se retrouve dans la source, que les chiffres y
figurent. Ils laissent passer un cas que la mesure a fini par exposer (ADR 0010) — à la
question « quelle est la capitale du Sénégal ? », le modèle répond « Dakar » en recopiant une
phrase authentique d'un document réel. La citation existe, elle se vérifie, et elle ne prouve
rien de ce qui est affirmé.

**Une citation qui existe n'est pas une citation qui prouve.** Aucune règle sur les caractères
ne comble cet écart : il faut lire le sens, donc demander au modèle. Ce contrôle est le seul
du projet à coûter un appel, et il est déclenché avec parcimonie (voir `reponse.py`) :
uniquement quand l'ancrage par les chiffres ne peut rien établir. Sur le jeu de mesure, cela
représente 15 % des réponses affirmatives — et la totalité des cas fautifs connus.

Le juge est **un modèle de 3 milliards de paramètres** : on lui pose une seule question,
fermée, et on retient le doute contre la réponse plutôt que contre le silence.
"""

from __future__ import annotations

import json
import logging
import re

from jurismind.llm import Vitesse, modele_chat

logger = logging.getLogger(__name__)

# Une seule question, fermée. Demander en plus « pourquoi ? » ou « quel degré de certitude ? »
# fait chuter la fiabilité d'un petit modèle, constaté sur l'extraction (ADR 0004). La
# dernière règle est celle qui compte : c'est elle qui rattrape « Dakar ».
CONSIGNE = """Tu relis le travail d'un assistant juridique.

Source :
{sources}

Affirmation : {affirmation}

Réponds uniquement par un objet JSON de cette forme :
{{"soutenue": true}}

Règles :
- "soutenue" vaut true seulement si la source ci-dessus dit explicitement ce qu'affirme la phrase.
- Une affirmation vraie dans la réalité mais absente de la source vaut false.
- Une affirmation qui parle d'un autre sujet que la source vaut false.
"""

_OUI = re.compile(r'"soutenue"\s*:\s*true', re.IGNORECASE)
_NON = re.compile(r'"soutenue"\s*:\s*false', re.IGNORECASE)


def source_soutient(affirmation: str, sources: str, vitesse: Vitesse = Vitesse.RAPIDE) -> bool:
    """La source établit-elle l'affirmation ? Le doute compte contre la réponse.

    Un verdict illisible renvoie `False`, donc provoque une abstention. C'est volontaire :
    ce contrôle n'est sollicité que sur des réponses déjà faiblement ancrées, et le projet
    préfère un silence de trop à une affirmation de trop. Le coût d'une abstention injustifiée
    est une recherche manuelle ; celui d'une invention affirmée est un acte mal rédigé.
    """
    if not affirmation.strip() or not sources.strip():
        return False

    invite = CONSIGNE.format(sources=sources, affirmation=affirmation.strip())
    try:
        brut = str(modele_chat(vitesse, json=True).invoke(invite).content).strip()
    except Exception as erreur:  # noqa: BLE001 - un juge tombé ne doit rien laisser passer
        logger.warning("Contrôle d'implication indisponible (%s) : la réponse est écartée.", erreur)
        return False

    try:
        verdict = json.loads(brut).get("soutenue")
        if isinstance(verdict, bool):
            return verdict
    except (json.JSONDecodeError, AttributeError):
        pass

    # Le modèle entoure parfois son JSON de texte, ou le rend mal formé. On relit le brut
    # plutôt que d'abandonner, mais un « true » et un « false » dans la même réponse ne
    # tranchent rien : c'est un doute, et le doute écarte.
    oui, non = bool(_OUI.search(brut)), bool(_NON.search(brut))
    if oui != non:
        return oui

    logger.info("Verdict d'implication illisible : %r", brut[:120])
    return False
