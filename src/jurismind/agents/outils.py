"""Ce que les agents ont le droit de lire, et comment.

Chaque outil prend la session ouverte **au nom de l'utilisateur** : PostgreSQL applique
l'isolation, et l'agent ne peut pas la contourner, même en écrivant une requête maladroite.

Ces outils renvoient des faits tirés de la base — dates, montants, statuts — que le modèle
n'a plus qu'à mettre en forme. Un fait lu en base ne peut pas être inventé.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from jurismind.db.models import (
    AccesDossier,
    Client,
    Communication,
    Contact,
    Document,
    Dossier,
    ElementCrm,
    Extraction,
    Partie,
    SensEchange,
    StatutDossier,
    StatutExtraction,
    TypeElementCrm,
    Utilisateur,
)


@dataclass
class Evenement:
    """Un fait daté du dossier, tiré de la base : rien ici n'est produit par un modèle."""

    date: date
    type: str  # document | echange | etape
    libelle: str
    detail: str | None = None
    document_id: int | None = None
    communication_id: int | None = None

    def ligne(self) -> str:
        detail = f" — {self.detail}" if self.detail else ""
        return f"{self.date:%d/%m/%Y} : {self.libelle}{detail}"


def fiche_dossier(session: Session, dossier_id: int) -> dict[str, Any] | None:
    """Carte d'identité du dossier. `None` si l'utilisateur n'y a pas accès."""
    dossier = session.get(Dossier, dossier_id)
    if dossier is None:
        return None  # invisible pour cet utilisateur : l'isolation a joué

    client = session.get(Client, dossier.client_id)
    parties = session.scalars(select(Partie).where(Partie.dossier_id == dossier_id)).all()
    documents = session.scalar(
        select(func.count()).select_from(Document).where(Document.dossier_id == dossier_id)
    )
    echanges = session.scalar(
        select(func.count()).select_from(Communication).where(Communication.dossier_id == dossier_id)
    )
    return {
        "reference": dossier.reference,
        "intitule": dossier.intitule,
        "client": client.nom if client else None,
        "type": str(dossier.type),
        "matiere": dossier.matiere,
        "statut": str(dossier.statut),
        "date_ouverture": dossier.date_ouverture,
        "date_cloture": dossier.date_cloture,
        "juridiction": dossier.juridiction,
        "numero_rg": dossier.numero_rg,
        "enjeu_fcfa": dossier.enjeu_fcfa,
        "confidentiel": dossier.confidentiel,
        "parties": [{"qualite": str(p.qualite), "nom": p.nom} for p in parties],
        "nombre_documents": documents or 0,
        "nombre_echanges": echanges or 0,
    }


def evenements_du_dossier(session: Session, dossier_id: int, limite: int = 60) -> list[Evenement]:
    """Chronologie du dossier, **construite par le code** à partir des dates en base."""
    evenements: list[Evenement] = []

    documents = session.scalars(
        select(Document).where(Document.dossier_id == dossier_id).order_by(Document.date_document)
    ).all()
    for document in documents:
        if document.date_document is None:
            continue
        sens_document = {"entrant": "reçu", "sortant": "envoyé", "interne": "rédigé"}
        evenements.append(
            Evenement(
                date=document.date_document,
                type="document",
                libelle=document.titre,
                detail=sens_document.get(str(document.sens)),
                document_id=document.id,
            )
        )

    echanges = session.scalars(
        select(Communication)
        .where(Communication.dossier_id == dossier_id)
        .order_by(Communication.date_echange)
    ).all()
    for echange in echanges:
        entrant = echange.sens is SensEchange.ENTRANT
        interlocuteur = echange.expediteur if entrant else next(iter(echange.destinataires or []), None)
        sens_echange = "reçu de" if entrant else "adressé à"
        evenements.append(
            Evenement(
                date=echange.date_echange.date(),
                type="echange",
                libelle=echange.objet or f"{echange.canal} sans objet",
                detail=f"{sens_echange} {interlocuteur}" if interlocuteur else None,
                communication_id=echange.id,
            )
        )

    evenements.sort(key=lambda evenement: evenement.date)
    return evenements[-limite:]


def donnees_extraites(session: Session, dossier_id: int) -> list[dict[str, Any]]:
    """Valeurs tirées des actes du dossier (montants, délais, parties), avec leur statut."""
    lignes = session.execute(
        select(Extraction, Document.titre)
        .join(Document, Extraction.document_id == Document.id)
        .where(Document.dossier_id == dossier_id)
        .order_by(Document.date_document)
    ).all()
    return [
        {
            "document": titre,
            "schema": extraction.schema,
            "donnees": {k: v for k, v in extraction.donnees.items() if v not in (None, "", [])},
            "relue": extraction.relue,
            "champs_douteux": extraction.champs_douteux,
        }
        for extraction, titre in lignes
    ]


def elements_crm_du_client(session: Session, client_id: int, limite: int = 8) -> list[dict[str, Any]]:
    """Ce que le CRM sait du client : opportunités, comptes rendus de rendez-vous, tâches."""
    elements = session.scalars(
        select(ElementCrm)
        .where(ElementCrm.client_id == client_id)
        .order_by(ElementCrm.date_element.desc())
        .limit(limite)
    ).all()
    return [
        {
            "type": str(element.type),
            "titre": element.titre,
            "contenu": element.contenu,
            "date": element.date_element,
            "statut": element.statut,
            "montant_fcfa": element.montant_fcfa,
        }
        for element in elements
    ]


# --------------------------------------------------------------- côté client (F6)


def trouver_client(session: Session, nom: str) -> int | None:
    """Retrouve un client par son nom, exactement puis approximativement.

    Sert à l'appel en ligne de commande et à l'API : l'avocat parle de « Sine Services »,
    pas de l'identifiant 12. Un nom qui désigne plusieurs clients ne renvoie rien : mieux
    vaut demander de préciser que se tromper de dossier.
    """
    exact = session.scalars(select(Client).where(func.lower(Client.nom) == nom.lower())).all()
    if len(exact) == 1:
        return int(exact[0].id)
    approches = session.scalars(select(Client).where(Client.nom.ilike(f"%{nom}%")).limit(5)).all()
    return int(approches[0].id) if len(approches) == 1 else None


def fiche_client(session: Session, client_id: int) -> dict[str, Any] | None:
    """Carte d'identité du client. `None` si l'utilisateur ne voit aucun de ses dossiers."""
    client = session.get(Client, client_id)
    if client is None:
        return None  # l'isolation a joué : aucun dossier de ce client ne lui est ouvert

    contacts = session.scalars(select(Contact).where(Contact.client_id == client_id)).all()
    dossiers = session.scalars(select(Dossier).where(Dossier.client_id == client_id)).all()
    return {
        "nom": client.nom,
        "type": str(client.type),
        "forme_juridique": client.forme_juridique,
        "rccm": client.rccm,
        "ninea": client.ninea,
        "ville": client.ville,
        "telephone": client.telephone,
        "email": client.email,
        "suivi_dans_le_crm": client.crm_id is not None,
        "contacts": [
            {"nom": f"{contact.prenom or ''} {contact.nom}".strip(), "fonction": contact.fonction}
            for contact in contacts
        ],
        # « visibles » et non « du client » : l'utilisateur ne compte que ce qu'il a le droit de voir.
        "dossiers_visibles": len(dossiers),
        "dossiers_en_cours": sum(1 for d in dossiers if d.statut is StatutDossier.EN_COURS),
        "enjeu_total_fcfa": sum(d.enjeu_fcfa or 0 for d in dossiers) or None,
    }


def _dernieres_activites(session: Session, dossier_ids: list[int]) -> dict[int, date]:
    """Date du dernier mouvement de chaque dossier : pièce reçue ou envoyée, ou échange."""
    if not dossier_ids:
        return {}
    dernieres: dict[int, date] = {}
    pieces = session.execute(
        select(Document.dossier_id, func.max(Document.date_document))
        .where(Document.dossier_id.in_(dossier_ids))
        .group_by(Document.dossier_id)
    ).all()
    echanges = session.execute(
        select(Communication.dossier_id, func.max(Communication.date_echange))
        .where(Communication.dossier_id.in_(dossier_ids))
        .group_by(Communication.dossier_id)
    ).all()
    for dossier_id, derniere in pieces:
        if derniere is not None:
            dernieres[dossier_id] = derniere
    for dossier_id, derniere in echanges:
        if derniere is None:
            continue
        connue = dernieres.get(dossier_id)
        if connue is None or derniere.date() > connue:
            dernieres[dossier_id] = derniere.date()
    return dernieres


def dossiers_du_client(session: Session, client_id: int) -> list[dict[str, Any]]:
    """Les dossiers du client **que l'utilisateur a le droit de voir**, du plus récent au plus ancien."""
    dossiers = session.scalars(
        select(Dossier)
        .where(Dossier.client_id == client_id)
        .order_by(Dossier.date_ouverture.desc(), Dossier.reference)
    ).all()
    dernieres = _dernieres_activites(session, [dossier.id for dossier in dossiers])
    responsables = {
        dossier_id: nom
        for dossier_id, nom in session.execute(
            select(AccesDossier.dossier_id, Utilisateur.nom_complet)
            .join(Utilisateur, Utilisateur.id == AccesDossier.utilisateur_id)
            .where(
                AccesDossier.dossier_id.in_([dossier.id for dossier in dossiers] or [0]),
                AccesDossier.est_responsable,
            )
        ).all()
    }
    return [
        {
            "id": dossier.id,
            "reference": dossier.reference,
            "intitule": dossier.intitule,
            "type": str(dossier.type),
            "matiere": dossier.matiere,
            "statut": str(dossier.statut),
            "date_ouverture": dossier.date_ouverture,
            "date_cloture": dossier.date_cloture,
            "juridiction": dossier.juridiction,
            "enjeu_fcfa": dossier.enjeu_fcfa,
            "responsable": responsables.get(dossier.id),
            "derniere_activite": dernieres.get(dossier.id),
        }
        for dossier in dossiers
    ]


def derniers_echanges(session: Session, client_id: int, limite: int = 8) -> list[dict[str, Any]]:
    """Les derniers échanges avec le client, tous dossiers confondus."""
    lignes = session.execute(
        select(Communication, Dossier.reference)
        .join(Dossier, Communication.dossier_id == Dossier.id)
        .where(Dossier.client_id == client_id)
        .order_by(Communication.date_echange.desc())
        .limit(limite)
    ).all()
    return [
        {
            "date": echange.date_echange.date(),
            "dossier": reference,
            "sens": "reçu" if echange.sens is SensEchange.ENTRANT else "envoyé",
            "canal": str(echange.canal),
            "objet": echange.objet,
            "interlocuteur": echange.expediteur
            if echange.sens is SensEchange.ENTRANT
            else next(iter(echange.destinataires or []), None),
        }
        for echange, reference in lignes
    ]


# ------------------------------------------------- points d'attention (calculés, non rédigés)

SILENCE_DOSSIER_JOURS = 60  # un dossier en cours qui ne bouge plus est un dossier qu'on oublie
ATTENTE_REPONSE_JOURS = 7  # un courrier du client resté sans réponse
DELAI_PROCHE_JOURS = 15  # un délai qui échoit bientôt
DELAI_RECENT_JOURS = 30  # un délai échu depuis peu : il peut encore être utile de le savoir
OPPORTUNITES_OUVERTES = ("qualification", "proposition", "negociation")
TACHES_OUVERTES = ("ouverte", "en_cours")

# Les champs d'extraction qui font courir un délai, et comment les nommer à l'avocat.
DELAIS = {
    "delai_opposition_jours": "Délai d'opposition",
    "delai_jours": "Délai de la mise en demeure",
    "delai_paiement_jours": "Délai de paiement",
}


@dataclass
class PointAttention:
    """Un fait qui mérite l'attention de l'avocat, **déduit des données** par une règle.

    Aucun point n'est produit par un modèle : chacun se vérifie en remontant à la date, au
    montant ou au statut qui l'a déclenché. On préfère une liste courte et sûre à une liste
    riche et douteuse.
    """

    gravite: str  # haute | moyenne
    libelle: str
    detail: str
    dossier: str | None = None

    def ligne(self) -> str:
        marque = "[!]" if self.gravite == "haute" else "[.]"
        ou = f" [{self.dossier}]" if self.dossier else ""
        return f"{marque} {self.libelle}{ou} — {self.detail}"


def _en_date(valeur: Any) -> date | None:
    """Les dates d'une extraction sont stockées en texte dans le JSON : on les relit prudemment."""
    if isinstance(valeur, date):
        return valeur
    if isinstance(valeur, str):
        try:
            return date.fromisoformat(valeur[:10])
        except ValueError:
            return None
    return None


def _jours(nombre: int) -> str:
    return "1 jour" if nombre == 1 else f"{nombre} jours"


def _points_delais(
    session: Session, dossier_ids: list[int], references: dict[int, str], aujourdhui: date
) -> list[PointAttention]:
    """Délais qui courent ou viennent d'échoir, reconstitués depuis les actes extraits."""
    points: list[PointAttention] = []
    lignes = session.execute(
        select(Extraction, Document.dossier_id, Document.date_document)
        .join(Document, Extraction.document_id == Document.id)
        .where(Document.dossier_id.in_(dossier_ids))
    ).all()
    for extraction, dossier_id, date_document in lignes:
        depart = (
            _en_date(extraction.donnees.get("date_signification"))
            or _en_date(extraction.donnees.get("date_acte"))
            or date_document
        )
        if depart is None:
            continue
        for champ, nom in DELAIS.items():
            jours = extraction.donnees.get(champ)
            if not isinstance(jours, int):
                continue
            echeance = depart + timedelta(days=jours)
            ecart = (echeance - aujourdhui).days
            if 0 <= ecart <= DELAI_PROCHE_JOURS:
                points.append(
                    PointAttention(
                        gravite="haute",
                        libelle=f"{nom} de {_jours(jours)}",
                        detail=f"échoit le {echeance:%d/%m/%Y}, dans {_jours(ecart)}",
                        dossier=references.get(dossier_id),
                    )
                )
            elif -DELAI_RECENT_JOURS <= ecart < 0:
                points.append(
                    PointAttention(
                        gravite="moyenne",
                        libelle=f"{nom} de {_jours(jours)}",
                        detail=f"échu le {echeance:%d/%m/%Y}, il y a {_jours(-ecart)}",
                        dossier=references.get(dossier_id),
                    )
                )
    return points


def _points_silence(dossiers: list[dict[str, Any]], aujourdhui: date) -> list[PointAttention]:
    """Dossiers en cours sans mouvement depuis longtemps."""
    points: list[PointAttention] = []
    for dossier in dossiers:
        if dossier["statut"] != str(StatutDossier.EN_COURS):
            continue
        derniere = dossier["derniere_activite"] or dossier["date_ouverture"]
        immobile = (aujourdhui - derniere).days
        if immobile > SILENCE_DOSSIER_JOURS:
            quoi = (
                "aucune pièce depuis l'ouverture" if not dossier["derniere_activite"] else "rien de nouveau"
            )
            points.append(
                PointAttention(
                    gravite="moyenne",
                    libelle="Dossier en sommeil",
                    detail=f"{quoi} depuis {_jours(immobile)} ({derniere:%d/%m/%Y})",
                    dossier=dossier["reference"],
                )
            )
    return points


def _points_sans_reponse(
    session: Session, dossier_ids: list[int], references: dict[int, str], aujourdhui: date
) -> list[PointAttention]:
    """Dossiers dont le dernier échange est entrant : quelqu'un attend une réponse."""
    points: list[PointAttention] = []
    for dossier_id in dossier_ids:
        dernier = session.scalars(
            select(Communication)
            .where(Communication.dossier_id == dossier_id)
            .order_by(Communication.date_echange.desc())
            .limit(1)
        ).first()
        if dernier is None or dernier.sens is not SensEchange.ENTRANT:
            continue
        attente = (aujourdhui - dernier.date_echange.date()).days
        if attente >= ATTENTE_REPONSE_JOURS:
            points.append(
                PointAttention(
                    gravite="haute" if attente >= 2 * ATTENTE_REPONSE_JOURS else "moyenne",
                    libelle="Dernier échange resté sans réponse",
                    detail=f"« {dernier.objet or 'sans objet'} » reçu il y a {_jours(attente)}",
                    dossier=references.get(dossier_id),
                )
            )
    return points


def _points_relecture(session: Session, dossier_ids: list[int]) -> list[PointAttention]:
    """Valeurs extraites jamais relues alors qu'elles sont signalées douteuses."""
    a_relire = session.execute(
        select(func.count())
        .select_from(Extraction)
        .join(Document, Extraction.document_id == Document.id)
        .where(
            Document.dossier_id.in_(dossier_ids),
            Extraction.statut == StatutExtraction.PROPOSEE,
            func.jsonb_array_length(Extraction.champs_douteux) > 0,
        )
    ).scalar()
    if not a_relire:
        return []
    return [
        PointAttention(
            gravite="moyenne",
            libelle="Valeurs extraites à relire",
            detail=f"{a_relire} document(s) avec des champs douteux non validés",
        )
    ]


def montant_lisible(montant: int) -> str:
    """13750000 → « 13 750 000 », comme l'écrit un acte."""
    return f"{montant:,}".replace(",", " ")


def _points_crm(session: Session, client_id: int) -> list[PointAttention]:
    """Ce que le CRM laisse en suspens : mandats en négociation, relances non faites."""
    points: list[PointAttention] = []
    elements = session.scalars(select(ElementCrm).where(ElementCrm.client_id == client_id)).all()
    for opportunite in elements:
        if opportunite.type is not TypeElementCrm.OPPORTUNITE:
            continue
        if (opportunite.statut or "") not in OPPORTUNITES_OUVERTES:
            continue
        montant = f", {montant_lisible(opportunite.montant_fcfa)} FCFA" if opportunite.montant_fcfa else ""
        points.append(
            PointAttention(
                gravite="moyenne",
                libelle="Mandat en cours de négociation",
                detail=f"« {opportunite.titre} » ({opportunite.statut}{montant})",
            )
        )
    taches = [
        element
        for element in elements
        if element.type is TypeElementCrm.TACHE and (element.statut or "") in TACHES_OUVERTES
    ]
    if taches:
        points.append(
            PointAttention(
                gravite="moyenne",
                libelle="Relances commerciales ouvertes dans le CRM",
                detail=", ".join(f"« {tache.titre} »" for tache in taches[:3]),
            )
        )
    return points


def points_attention(
    session: Session,
    client_id: int,
    dossiers: list[dict[str, Any]] | None = None,
    aujourdhui: date | None = None,
) -> list[PointAttention]:
    """Ce que l'avocat devrait regarder chez ce client, déduit des données visibles par lui.

    `aujourdhui` est explicite pour que les règles soient rejouables à l'identique en test.
    """
    aujourdhui = aujourdhui or datetime.now(UTC).date()
    dossiers = dossiers if dossiers is not None else dossiers_du_client(session, client_id)
    dossier_ids = [dossier["id"] for dossier in dossiers]
    references = {dossier["id"]: dossier["reference"] for dossier in dossiers}

    points: list[PointAttention] = []
    if dossier_ids:
        points += _points_delais(session, dossier_ids, references, aujourdhui)
        points += _points_sans_reponse(session, dossier_ids, references, aujourdhui)
        points += _points_relecture(session, dossier_ids)
    points += _points_silence(dossiers, aujourdhui)
    points += _points_crm(session, client_id)

    points.sort(key=lambda point: (point.gravite != "haute", point.libelle, point.dossier or ""))
    return points
