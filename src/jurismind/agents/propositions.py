"""Le cycle de vie d'une proposition : proposée → tranchée par un humain → appliquée.

Pourquoi une table et non `interrupt()` de LangGraph. `interrupt()` suspend l'exécution d'un
graphe dans un point de reprise, et attend la réponse pour continuer. C'est le bon outil quand
la confirmation arrive dans la seconde, au sein de la même session. Dans un cabinet, elle
arrive le lendemain, elle est donnée par **quelqu'un d'autre** que celui qui a lancé le tri, et
elle doit laisser une trace consultable des mois plus tard. Une ligne en base répond aux trois ;
un point de reprise en mémoire à aucune.

Trois effets seulement, et chacun est réversible ou inoffensif :

- **rattachement** : écrit `dossier_id` sur l'échange et sur ses extraits, pour que la recherche
  le retrouve dans le dossier. Réversible.
- **brouillon** : validé, il est *approuvé pour envoi* — JurisMind n'envoie rien lui-même.
- **tâche CRM** : seul effet hors du cabinet, donc le seul qui puisse échouer.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from jurismind.agents.indices import societe_de
from jurismind.connectors.crm import ApiCrm, CrmIndisponible, nom_comparable
from jurismind.db.models import (
    Communication,
    Confiance,
    Extrait,
    Proposition,
    StatutProposition,
    TypeProposition,
    Utilisateur,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Decision:
    """État d'une proposition, lisible après la fermeture de la session.

    Rendre la ligne ORM elle-même serait un piège : une fois la session refermée, lire
    `proposition.statut` lève `DetachedInstanceError`. L'API REST et la démo recevront
    donc des données, pas un objet vivant.
    """

    id: int
    type: TypeProposition
    statut: StatutProposition
    titre: str
    justification: str
    confiance: Confiance
    dossier_id: int | None = None
    contenu: str | None = None
    # Qui a autorisé, et quand : c'est ce qu'on viendra relire dans six mois.
    decide_par_id: int | None = None
    decide_le: datetime | None = None
    erreur: str | None = None
    donnees: dict[str, Any] = field(default_factory=dict)


def decision_de(proposition: Proposition) -> Decision:
    return Decision(
        id=proposition.id,
        type=proposition.type,
        statut=proposition.statut,
        titre=proposition.titre,
        justification=proposition.justification,
        confiance=proposition.confiance,
        dossier_id=proposition.dossier_id,
        contenu=proposition.contenu,
        decide_par_id=proposition.decide_par_id,
        decide_le=proposition.decide_le,
        erreur=proposition.erreur,
        donnees=dict(proposition.donnees),
    )


class PropositionIntrouvable(LookupError):
    """La proposition n'existe pas, ou l'utilisateur n'a pas le droit de la voir."""


class DejaTranchee(RuntimeError):
    """Un humain s'est déjà prononcé : on ne revient pas sur sa décision en silence."""


def enregistrer(
    session: Session,
    type_proposition: TypeProposition,
    titre: str,
    justification: str,
    confiance: Confiance,
    communication_id: int | None = None,
    dossier_id: int | None = None,
    client_id: int | None = None,
    contenu: str | None = None,
    donnees: dict[str, Any] | None = None,
) -> Proposition:
    """Dépose une proposition. Toujours une justification : une proposition sans raison n'en est pas une."""
    if not justification.strip():
        raise ValueError("une proposition doit dire sur quoi elle se fonde")
    proposition = Proposition(
        type=type_proposition,
        communication_id=communication_id,
        dossier_id=dossier_id,
        client_id=client_id,
        titre=titre[:300],
        contenu=contenu,
        justification=justification[:500],
        confiance=confiance,
        donnees=donnees or {},
    )
    session.add(proposition)
    session.flush()
    return proposition


def deja_proposee(session: Session, communication_id: int, type_proposition: TypeProposition) -> bool:
    """Le tri est rejouable : on ne redépose pas ce qui attend déjà une décision."""
    return bool(
        session.scalar(
            select(func.count())
            .select_from(Proposition)
            .where(
                Proposition.communication_id == communication_id,
                Proposition.type == type_proposition,
                Proposition.statut == StatutProposition.PROPOSEE,
            )
        )
    )


def a_trancher(session: Session, limite: int = 50) -> list[Decision]:
    """Ce qui attend une décision, les propositions les plus sûres d'abord."""
    ordre = {Confiance.HAUTE: 0, Confiance.MOYENNE: 1, Confiance.FAIBLE: 2}
    propositions = session.scalars(
        select(Proposition)
        .where(Proposition.statut == StatutProposition.PROPOSEE)
        .order_by(Proposition.id)
        .limit(limite)
    ).all()
    rangees = sorted(propositions, key=lambda proposition: ordre[proposition.confiance])
    return [decision_de(proposition) for proposition in rangees]


def _charger(session: Session, proposition_id: int) -> Proposition:
    proposition = session.get(Proposition, proposition_id)
    if proposition is None:
        # Soit elle n'existe pas, soit elle vise un dossier que l'utilisateur ne voit pas.
        raise PropositionIntrouvable(f"proposition {proposition_id}")
    return proposition


def rejeter(session: Session, proposition_id: int, utilisateur_id: int, motif: str = "") -> Decision:
    """Un humain dit non. Rien ne se produit, et on garde qui a dit non."""
    proposition = _charger(session, proposition_id)
    if proposition.tranchee:
        raise DejaTranchee(f"proposition {proposition_id} déjà {proposition.statut}")
    proposition.statut = StatutProposition.REJETEE
    proposition.decide_par_id = utilisateur_id
    proposition.decide_le = datetime.now(UTC)
    if motif:
        proposition.donnees = {**proposition.donnees, "motif_du_rejet": motif[:300]}
    session.flush()
    logger.info("Proposition %s rejetée", proposition_id)
    return decision_de(proposition)


def valider(
    session: Session, proposition_id: int, utilisateur_id: int, api: ApiCrm | None = None
) -> Decision:
    """Un humain dit oui : on enregistre sa décision, puis on produit l'effet."""
    proposition = _charger(session, proposition_id)
    if proposition.tranchee:
        raise DejaTranchee(f"proposition {proposition_id} déjà {proposition.statut}")
    proposition.statut = StatutProposition.VALIDEE
    proposition.decide_par_id = utilisateur_id
    proposition.decide_le = datetime.now(UTC)
    session.flush()
    return _appliquer(session, proposition, api=api)


def appliquer(session: Session, proposition_id: int, api: ApiCrm | None = None) -> Decision:
    """Rejoue l'application d'une proposition déjà validée dont l'effet avait échoué."""
    return _appliquer(session, _charger(session, proposition_id), api=api)


def _appliquer(session: Session, proposition: Proposition, api: ApiCrm | None = None) -> Decision:
    """Produit l'effet d'une proposition validée. Rejouable si elle avait échoué."""
    if proposition.statut not in (StatutProposition.VALIDEE, StatutProposition.ECHOUEE):
        raise DejaTranchee(f"proposition {proposition.id} n'est pas validée ({proposition.statut})")

    try:
        if proposition.type is TypeProposition.RATTACHEMENT:
            _rattacher(session, proposition)
        elif proposition.type is TypeProposition.TACHE_CRM:
            _creer_tache_crm(session, proposition, api)
        else:
            # Un brouillon validé est approuvé pour envoi : c'est un humain qui l'envoie.
            logger.info("Brouillon %s approuvé pour envoi", proposition.id)
    except (CrmIndisponible, ValueError, LookupError) as erreur:
        proposition.statut = StatutProposition.ECHOUEE
        proposition.erreur = str(erreur)[:500]
        session.flush()
        logger.warning("Proposition %s : application échouée (%s)", proposition.id, erreur)
        return decision_de(proposition)

    proposition.statut = StatutProposition.APPLIQUEE
    proposition.erreur = None
    session.flush()
    return decision_de(proposition)


def _rattacher(session: Session, proposition: Proposition) -> None:
    """Rattache l'échange au dossier — et ses extraits avec lui, sinon la recherche l'ignore."""
    if proposition.communication_id is None or proposition.dossier_id is None:
        raise ValueError("un rattachement exige un échange et un dossier")
    echange = session.get(Communication, proposition.communication_id)
    if echange is None:
        raise LookupError(f"échange {proposition.communication_id} introuvable")
    echange.dossier_id = proposition.dossier_id
    session.execute(
        update(Extrait)
        .where(Extrait.communication_id == proposition.communication_id)
        .values(dossier_id=proposition.dossier_id)
    )
    session.flush()
    logger.info("Échange %s rattaché au dossier %s", echange.id, proposition.dossier_id)


def _compte_crm(api: ApiCrm, societe: str) -> str:
    """Identifiant du compte CRM portant ce nom. Résolu au moment d'écrire, pas avant."""
    cherche = nom_comparable(societe)
    for compte in api.lister("accounts"):
        if nom_comparable(str(compte.get("name", ""))) == cherche:
            return str(compte["id"])
    raise LookupError(f"aucun compte CRM nommé « {societe} »")


def _creer_tache_crm(session: Session, proposition: Proposition, api: ApiCrm | None) -> None:
    """Crée la tâche de suivi dans le CRM du cabinet. Seul effet visible hors du cabinet."""
    societe = str(proposition.donnees.get("societe") or "")
    echeance = str(proposition.donnees.get("echeance") or "")
    if not societe or not echeance:
        raise ValueError("une tâche CRM exige une société et une échéance")

    responsable = str(proposition.donnees.get("responsable") or "")
    if not responsable and proposition.decide_par_id is not None:
        responsable = (
            session.scalars(
                select(Utilisateur.email).where(Utilisateur.id == proposition.decide_par_id)
            ).first()
            or ""
        )

    client = api or ApiCrm()
    try:
        cree = client.post(
            "tasks",
            {
                "account_id": _compte_crm(client, societe),
                "title": proposition.titre,
                "due_date": echeance,
                "owner": responsable,
            },
        )
    finally:
        if api is None:
            client.http.close()
    proposition.donnees = {**proposition.donnees, "crm_task_id": cree.get("id")}
    session.flush()


def tache_pour_prospect(
    echange: Communication, resume: str, echeance: str, societe: str | None = None
) -> dict[str, Any]:
    """Les données d'une tâche de rappel pour quelqu'un qui n'a pas encore de dossier."""
    nom = societe or societe_de(echange.expediteur) or (echange.expediteur or "contact inconnu")
    return {
        "societe": nom,
        "echeance": echeance,
        "demande": (echange.objet or "")[:200],
        "resume": resume[:500],
    }
