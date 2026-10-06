"""À quel dossier rattacher un échange, et avec quelle urgence le traiter.

Rien ici n'est demandé à un modèle. Un email mal rattaché va dans le dossier d'un autre
client : c'est une fuite, pas une imprécision. On cherche donc des **indices nommés**, on
retient le plus fort, et on ne retient rien quand deux indices de même force désignent des
dossiers différents — comme le rapprochement du CRM (ADR 0002).

Les indices, du plus fiable au moins fiable :

1. `reference_dossier`   la référence du dossier est écrite dans l'échange
2. `numero_role`         un numéro de rôle ou d'ordonnance cité renvoie à un seul dossier
3. `partie_au_dossier`   l'expéditeur est une partie du dossier (confrère, huissier)
4. `contact_et_adverse`  l'expéditeur est un contact du client, et l'adversaire est nommé
5. `contact_dossier_unique`  l'expéditeur est un contact d'un client qui n'a qu'un dossier ouvert
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass
from datetime import date, timedelta
from enum import StrEnum

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from jurismind.core.texte import normaliser, references_brutes
from jurismind.db.models import (
    Communication,
    Confiance,
    Contact,
    Document,
    Dossier,
    Partie,
    QualitePartie,
    StatutDossier,
)

# Les références du cabinet : D2026-0024.
REFERENCE_DOSSIER = re.compile(r"\bD\d{4}-\d{4}\b", re.IGNORECASE)

# Mots qui font d'un échange une urgence : une date de comparution ou un délai qui court.
MOTS_URGENTS = (
    "audience",
    "comparution",
    "convocation",
    "assignation",
    "mise en demeure",
    "injonction",
    "opposition",
    "saisie",
    "expulsion",
    "delai de",
    "urgent",
    "sous huitaine",
)
# Qualités dont un courrier engage une procédure en cours.
QUALITES_PROCEDURE = (QualitePartie.AVOCAT_ADVERSE, QualitePartie.HUISSIER)
# Un mot de moins de 5 lettres ne distingue pas une société d'une autre.
LONGUEUR_MOT_UTILE = 5


class Priorite(StrEnum):
    HAUTE = "haute"
    MOYENNE = "moyenne"
    BASSE = "basse"


@dataclass(frozen=True)
class Candidat:
    """Un dossier possible, et l'indice qui le désigne."""

    dossier_id: int
    reference: str
    indice: str
    confiance: Confiance

    def justification(self) -> str:
        explications = {
            "reference_dossier": f"la référence {self.reference} est citée dans l'échange",
            "numero_role": f"le numéro de rôle cité renvoie au dossier {self.reference}",
            "partie_au_dossier": f"l'expéditeur est une partie du dossier {self.reference}",
            "contact_et_adverse": (
                f"l'expéditeur est un contact du client et l'adversaire du dossier "
                f"{self.reference} est nommé dans l'échange"
            ),
            "contact_dossier_unique": (
                f"l'expéditeur est un contact du client, qui n'a que le dossier {self.reference} en cours"
            ),
        }
        return explications.get(self.indice, f"indice {self.indice} vers {self.reference}")


def texte_de(echange: Communication) -> str:
    return f"{echange.objet or ''}\n{echange.corps or ''}"


def societe_de(email: str | None) -> str | None:
    """Nom de société devinée depuis le domaine : « lamine@casamance-services-sarl.example ».

    Sert uniquement à nommer un prospect dans une proposition de tâche ; aucune décision de
    rattachement ne repose là-dessus.
    """
    if not email or "@" not in email:
        return None
    domaine = email.rsplit("@", 1)[1].lower()
    etiquettes = [part for part in domaine.split(".") if part not in ("example", "com", "sn", "org")]
    if not etiquettes:
        return None
    mots = etiquettes[0].replace("_", "-").split("-")
    formes = {
        "sarl": "SARL",
        "sa": "SA",
        "suarl": "SUARL",
        "gie": "GIE",
        "sas": "SAS",
        "sci": "SCI",
        "btp": "BTP",
    }
    return " ".join(formes.get(mot, mot.capitalize()) for mot in mots if mot) or None


def _par_reference(session: Session, texte: str) -> list[Candidat]:
    """Le cas le plus simple : la référence du dossier est écrite noir sur blanc."""
    citees = {reference.upper() for reference in REFERENCE_DOSSIER.findall(texte)}
    if not citees:
        return []
    dossiers = session.scalars(select(Dossier).where(Dossier.reference.in_(citees))).all()
    return [
        Candidat(dossier.id, dossier.reference, "reference_dossier", Confiance.HAUTE) for dossier in dossiers
    ]


def _par_numero(session: Session, texte: str) -> list[Candidat]:
    """Un numéro de rôle ou d'ordonnance (« 279/2026 ») cité dans l'échange."""
    numeros = {normaliser(reference) for reference in references_brutes(texte)}
    if not numeros:
        return []
    candidats: list[Candidat] = []
    dossiers = session.scalars(select(Dossier).where(Dossier.numero_rg.is_not(None))).all()
    for dossier in dossiers:
        if normaliser(dossier.numero_rg or "") and any(
            numero in normaliser(dossier.numero_rg or "") for numero in numeros
        ):
            candidats.append(Candidat(dossier.id, dossier.reference, "numero_role", Confiance.HAUTE))
    if candidats:
        return candidats
    # Sinon, le numéro peut figurer dans le titre d'une pièce du dossier (une ordonnance).
    pieces = session.execute(
        select(Document.dossier_id, Dossier.reference, Document.titre)
        .join(Dossier, Document.dossier_id == Dossier.id)
        .where(Document.titre.is_not(None))
    ).all()
    vus: set[int] = set()
    for dossier_id, reference, titre in pieces:
        if dossier_id in vus:
            continue
        if any(numero in normaliser(titre) for numero in numeros):
            candidats.append(Candidat(dossier_id, reference, "numero_role", Confiance.MOYENNE))
            vus.add(dossier_id)
    return candidats


def _par_partie(session: Session, email: str | None) -> list[Candidat]:
    """L'expéditeur est déjà connu comme partie d'un dossier : confrère, huissier, tiers."""
    if not email:
        return []
    lignes = session.execute(
        select(Partie.dossier_id, Dossier.reference)
        .join(Dossier, Partie.dossier_id == Dossier.id)
        .where(func.lower(Partie.email) == email.lower())
    ).all()
    return [
        Candidat(dossier_id, reference, "partie_au_dossier", Confiance.HAUTE)
        for dossier_id, reference in lignes
    ]


def _mots_significatifs(texte: str) -> set[str]:
    return {mot for mot in normaliser(texte).split() if len(mot) >= LONGUEUR_MOT_UTILE}


def _discriminants(mots_par_dossier: dict[int, set[str]]) -> dict[int, set[str]]:
    """Garde, pour chaque dossier, les mots qu'aucun autre ne partage.

    Les noms de sociétés sénégalaises partagent beaucoup : « Immobilier », « Services »,
    « Distribution ». Un mot présent chez deux adversaires du même client ne permet pas
    de choisir entre leurs dossiers, donc il ne vaut pas comme indice.
    """
    compte = Counter(mot for mots in mots_par_dossier.values() for mot in mots)
    return {dossier: {mot for mot in mots if compte[mot] == 1} for dossier, mots in mots_par_dossier.items()}


def _par_contact(session: Session, email: str | None, texte: str) -> list[Candidat]:
    """L'expéditeur travaille chez un client : reste à savoir de quel dossier il parle."""
    if not email:
        return []
    contact = session.scalars(select(Contact).where(func.lower(Contact.email) == email.lower())).first()
    if contact is None:
        return []
    dossiers = session.scalars(
        select(Dossier).where(
            Dossier.client_id == contact.client_id,
            Dossier.statut == StatutDossier.EN_COURS,
        )
    ).all()
    if not dossiers:
        return []

    # L'adversaire nommé dans l'échange désigne le dossier — à condition que le mot qui
    # le désigne soit propre à ce dossier. « Immobilier » est commun à « Cap-Vert
    # Immobilier » et « Baobab Immobilier » : il ne distingue rien, et s'y fier
    # rattachait l'échange aux deux dossiers à la fois.
    adverses = {
        dossier.id: _mots_significatifs(
            " ".join(
                partie.nom
                for partie in session.scalars(
                    select(Partie).where(
                        Partie.dossier_id == dossier.id,
                        Partie.qualite == QualitePartie.ADVERSE,
                    )
                ).all()
            )
        )
        for dossier in dossiers
    }
    mots = _mots_significatifs(texte)
    candidats = [
        Candidat(dossier.id, dossier.reference, "contact_et_adverse", Confiance.HAUTE)
        for dossier in dossiers
        for discriminants in [_discriminants(adverses)[dossier.id]]
        if discriminants & mots
    ]
    if candidats:
        return candidats
    if len(dossiers) == 1:
        return [Candidat(dossiers[0].id, dossiers[0].reference, "contact_dossier_unique", Confiance.MOYENNE)]
    return []  # plusieurs dossiers ouverts et rien pour trancher : on ne devine pas


def candidats(session: Session, echange: Communication) -> list[Candidat]:
    """Tous les indices trouvés pour cet échange, du plus fort au plus faible."""
    texte = texte_de(echange)
    trouves = (
        _par_reference(session, texte)
        + _par_numero(session, texte)
        + _par_partie(session, echange.expediteur)
        + _par_contact(session, echange.expediteur, texte)
    )
    ordre = {Confiance.HAUTE: 0, Confiance.MOYENNE: 1, Confiance.FAIBLE: 2}
    return sorted(trouves, key=lambda candidat: ordre[candidat.confiance])


def retenir(trouves: list[Candidat]) -> Candidat | None:
    """Le meilleur candidat, ou rien si deux indices de même force se contredisent."""
    if not trouves:
        return None
    meilleurs = [candidat for candidat in trouves if candidat.confiance is trouves[0].confiance]
    dossiers = {candidat.dossier_id for candidat in meilleurs}
    return meilleurs[0] if len(dossiers) == 1 else None


def priorite(session: Session, echange: Communication, candidat: Candidat | None) -> tuple[Priorite, str]:
    """Avec quelle urgence traiter cet échange, et pourquoi."""
    texte = normaliser(texte_de(echange))
    urgents = [mot for mot in MOTS_URGENTS if normaliser(mot) in texte]
    if urgents:
        return Priorite.HAUTE, f"l'échange parle de : {', '.join(urgents[:3])}"

    if candidat is not None:
        partie = session.scalars(
            select(Partie).where(
                Partie.dossier_id == candidat.dossier_id,
                func.lower(Partie.email) == (echange.expediteur or "").lower(),
                Partie.qualite.in_(QUALITES_PROCEDURE),
            )
        ).first()
        if partie is not None:
            return Priorite.HAUTE, f"l'expéditeur est {partie.qualite} au dossier"
        return Priorite.MOYENNE, f"échange sur le dossier {candidat.reference}, en cours"
    return Priorite.BASSE, "aucun dossier en cours concerné"


def echeance_relance(aujourdhui: date, jours: int = 2) -> date:
    """Quand rappeler un prospect : assez tôt pour que la demande ne refroidisse pas."""
    return aujourdhui + timedelta(days=jours)
