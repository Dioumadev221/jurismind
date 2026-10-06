"""Ce que tous les agents partagent : la forme de leur réponse, la lecture du JSON produit
par le modèle, et l'inscription au journal d'audit.

Un seul format de réponse pour tous les agents : c'est ce que l'API REST (F10) exposera,
et ce que la démo affichera, sans avoir à savoir quel agent a répondu.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.orm import Session

from jurismind.core.texte import normaliser
from jurismind.db.models import EntreeAudit
from jurismind.rag.verification import chiffres_ancres, chiffres_de


@dataclass
class ReponseAgent:
    """Ce qu'un agent rend à l'appelant."""

    intention: str
    texte: str
    citations: list[dict[str, Any]] = field(default_factory=list)
    # Les faits structurés derrière la réponse : chronologie, fiche, points d'attention…
    donnees: dict[str, Any] = field(default_factory=dict)
    abstention: bool = False
    secondes: float = 0.0


def lire_json(brut: str) -> dict[str, Any]:
    """Isole l'objet JSON d'une réponse de modèle, même entouré de bavardage.

    Renvoie `{}` si rien n'est lisible : l'appelant traite ce cas comme une abstention,
    jamais comme une réponse vide à afficher.
    """
    try:
        return dict(json.loads(brut))
    except (ValueError, TypeError):
        debut, fin = brut.find("{"), brut.rfind("}")
        if debut == -1 or fin <= debut:
            return {}
        try:
            return dict(json.loads(brut[debut : fin + 1]))
        except (ValueError, TypeError):
            return {}


def texte_attendu(donnees: dict[str, Any], cle: str) -> str:
    """Lit une valeur de texte dans la réponse du modèle, en tolérant la clé de travers.

    Mesuré sur `qwen2.5:3b` : à qui l'on demande `{"synthese": …}`, il répond volontiers
    `{"synthèse": …}` — le contenu est bon, seule l'orthographe de la clé a dérivé. On
    compare donc les clés sans accents ni ponctuation, et à défaut on accepte l'unique
    valeur de texte présente. Ce qui suit (vérification des chiffres, abstention) reste
    inchangé : on tolère la forme, jamais le fond.
    """
    attendue = normaliser(cle)
    for nom, valeur in donnees.items():
        if normaliser(str(nom)) == attendue and isinstance(valeur, str):
            return valeur.strip()
    textes = [valeur.strip() for valeur in donnees.values() if isinstance(valeur, str) and valeur.strip()]
    return textes[0] if len(textes) == 1 else ""


def liste_attendue(donnees: dict[str, Any], cle: str) -> list[Any]:
    """Lit une liste dans la réponse du modèle, en tolérant la clé de travers.

    Même tolérance que `texte_attendu`, et même limite : si plusieurs listes sont
    présentes sans qu'aucune clé ne corresponde, on ne devine pas.
    """
    attendue = normaliser(cle)
    for nom, valeur in donnees.items():
        if normaliser(str(nom)) == attendue and isinstance(valeur, list):
            return list(valeur)
    listes = [valeur for valeur in donnees.values() if isinstance(valeur, list)]
    return list(listes[0]) if len(listes) == 1 else []


def chiffres_douteux(texte: str, materiaux: str) -> bool:
    """Vrai si le texte avance un chiffre qui ne figure pas dans ce qu'on a fourni au modèle.

    Un texte **sans aucun chiffre** n'est pas douteux : il n'avance rien de vérifiable par
    ce moyen. `chiffres_ancres` répond « non ancré » dans ce cas, ce qui est juste pour une
    réponse citée — un montant demandé doit venir d'une source — mais faux pour une prose
    qui a pour consigne de ne citer aucun montant.
    """
    return bool(chiffres_de(texte)) and not chiffres_ancres(texte, materiaux)


def inscrire_au_journal(
    session: Session,
    utilisateur_id: int,
    action: str,
    details: dict[str, Any],
    dossier_id: int | None = None,
) -> None:
    """Trace un passage d'agent. Le cabinet doit pouvoir dire qui a demandé quoi, et quand."""
    session.add(
        EntreeAudit(
            utilisateur_id=utilisateur_id,
            action=action,
            dossier_id=dossier_id,
            details=details,
        )
    )
    session.flush()
