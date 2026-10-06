"""Vérification des conflits d'intérêts.

Un avocat ne peut pas agir contre son propre client, ni contre un ancien client dans une
affaire liée. C'est une obligation déontologique, pas un confort : la sanction est
disciplinaire, et elle peut faire écarter le cabinet de l'affaire.

**Deux inversions par rapport au reste du projet.**

1. *On préfère l'excès de signalement.* Ailleurs, un faux positif est le danger — fusionner
   deux clients homonymes, rattacher un email au mauvais dossier. Ici c'est le **faux
   négatif** : un conflit manqué est une faute, un conflit signalé à tort est une minute de
   vérification. Le contrôle est donc volontairement large, et classe ce qu'il trouve au
   lieu de trancher.

2. *Le contrôle franchit l'isolation.* Si Me Dieng n'interrogeait que ses propres dossiers,
   il ne verrait pas que le cabinet défend déjà la partie qu'il s'apprête à attaquer. Le
   balayage se fait donc avec la connexion propriétaire — c'est l'une des rares raisons
   légitimes de passer outre le RLS, et la règle de l'ordre l'exige : un cabinet tient un
   registre des conflits consultable par tous ses avocats. En contrepartie, le résultat
   **révèle le minimum** : le nom du client en cause et le fait qu'il soit actuel ou ancien,
   mais les références de dossiers ne sont nommées que si le demandeur y a déjà accès. Le
   reste est compté, pas détaillé. Et chaque vérification est inscrite au journal.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import StrEnum

from sqlalchemy import select
from sqlalchemy.orm import Session

from jurismind.connectors.crm import nom_comparable
from jurismind.core.texte import normaliser
from jurismind.db.models import (
    AccesDossier,
    Client,
    Contact,
    Dossier,
    EntreeAudit,
    Partie,
    QualitePartie,
    StatutDossier,
)
from jurismind.db.session import get_engine

logger = logging.getLogger(__name__)

# Qualités qui mettent le cabinet en face de quelqu'un.
QUALITES_OPPOSEES = (QualitePartie.ADVERSE,)


class Niveau(StrEnum):
    """Certitude de l'**identité**, pas gravité du conflit : les deux axes sont distincts."""

    CERTAIN = "certain"  # même nom, forme juridique comprise, ou mêmes coordonnées
    A_VERIFIER = "a_verifier"  # même nom une fois la forme retirée : à trancher par un humain


class Relation:
    """Gravité du conflit : agir contre un client actuel est plus grave que contre un ancien."""

    ACTUEL = "client actuel"
    ANCIEN = "ancien client"


@dataclass(frozen=True)
class Conflit:
    """Une collision entre une partie adverse et un client du cabinet."""

    niveau: Niveau
    motif: str  # nom_identique | nom_sans_forme_juridique | coordonnee_commune
    partie: str  # le nom vérifié
    client: str  # le client du cabinet en cause
    relation: str  # client actuel ou ancien
    explication: str
    # Dossiers nommés uniquement si le demandeur y a déjà accès ; les autres sont comptés.
    dossiers_visibles: list[str] = field(default_factory=list)
    autres_dossiers: int = 0

    def ligne(self) -> str:
        marque = "!!" if self.niveau is Niveau.CERTAIN else "! "
        ou = f" [{', '.join(self.dossiers_visibles)}]" if self.dossiers_visibles else ""
        autres = f" (+{self.autres_dossiers} dossier(s) non visibles)" if self.autres_dossiers else ""
        return f"{marque} {self.partie} ≈ {self.client} ({self.relation}){ou}{autres} — {self.explication}"


@dataclass(frozen=True)
class Identite:
    """Ce qu'on sait de la personne à vérifier."""

    nom: str
    email: str | None = None
    telephone: str | None = None


def _coordonnees(valeur: str | None) -> str | None:
    """Email ou téléphone sous forme comparable, ou rien si la valeur est vide."""
    propre = normaliser(valeur or "").replace(" ", "")
    return propre or None


def _relation(session: Session, client_id: int) -> str:
    ouvert = session.scalars(
        select(Dossier.id)
        .where(Dossier.client_id == client_id, Dossier.statut == StatutDossier.EN_COURS)
        .limit(1)
    ).first()
    return Relation.ACTUEL if ouvert else Relation.ANCIEN


def _dossiers_du_client(session: Session, client_id: int, autorises: set[int]) -> tuple[list[str], int]:
    """Références des dossiers du client : nommées si le demandeur y a accès, comptées sinon."""
    lignes = session.execute(
        select(Dossier.id, Dossier.reference).where(Dossier.client_id == client_id)
    ).all()
    visibles = sorted(reference for identifiant, reference in lignes if identifiant in autorises)
    return visibles, len(lignes) - len(visibles)


def _autorises(session: Session, utilisateur_id: int) -> set[int]:
    return set(
        session.scalars(
            select(AccesDossier.dossier_id).where(AccesDossier.utilisateur_id == utilisateur_id)
        ).all()
    )


def _coordonnees_des_clients(session: Session) -> dict[str, Client]:
    """Emails et téléphones connus du cabinet, par client — y compris ceux des contacts."""
    index: dict[str, Client] = {}
    for client in session.scalars(select(Client)).all():
        for valeur in (client.email, client.telephone):
            if (cle := _coordonnees(valeur)) is not None:
                index.setdefault(cle, client)
    for contact, client in session.execute(
        select(Contact, Client).join(Client, Contact.client_id == Client.id)
    ).all():
        for valeur in (contact.email, contact.telephone):
            if (cle := _coordonnees(valeur)) is not None:
                index.setdefault(cle, client)
    return index


def verifier(session: Session, identite: Identite, autorises: set[int]) -> list[Conflit]:
    """Collisions entre cette identité et les clients du cabinet. La session voit **tout**."""
    trouves: list[Conflit] = []
    vus: set[int] = set()

    exact = normaliser(identite.nom)
    sans_forme = nom_comparable(identite.nom)
    if not sans_forme:
        return []

    for client in session.scalars(select(Client)).all():
        if normaliser(client.nom) == exact:
            niveau, motif = Niveau.CERTAIN, "nom_identique"
            explication = "nom identique, forme juridique comprise"
        elif nom_comparable(client.nom) == sans_forme:
            niveau, motif = Niveau.A_VERIFIER, "nom_sans_forme_juridique"
            explication = f"même dénomination, forme juridique différente ({identite.nom} / {client.nom})"
        else:
            continue
        visibles, autres = _dossiers_du_client(session, client.id, autorises)
        trouves.append(
            Conflit(
                niveau=niveau,
                motif=motif,
                partie=identite.nom,
                client=client.nom,
                relation=_relation(session, client.id),
                explication=explication,
                dossiers_visibles=visibles,
                autres_dossiers=autres,
            )
        )
        vus.add(client.id)

    # Une coordonnée partagée identifie mieux qu'un nom : deux sociétés peuvent s'appeler
    # pareil, elles partagent rarement une adresse électronique.
    index = _coordonnees_des_clients(session)
    for valeur in (identite.email, identite.telephone):
        cle = _coordonnees(valeur)
        correspondant = index.get(cle) if cle else None
        if correspondant is None or correspondant.id in vus:
            continue
        visibles, autres = _dossiers_du_client(session, correspondant.id, autorises)
        trouves.append(
            Conflit(
                niveau=Niveau.CERTAIN,
                motif="coordonnee_commune",
                partie=identite.nom,
                client=correspondant.nom,
                relation=_relation(session, correspondant.id),
                explication=f"coordonnée partagée avec le client ({valeur})",
                dossiers_visibles=visibles,
                autres_dossiers=autres,
            )
        )
        vus.add(correspondant.id)

    trouves.sort(key=lambda conflit: (conflit.niveau is not Niveau.CERTAIN, conflit.client))
    return trouves


def _journaliser(session: Session, utilisateur_id: int, action: str, details: dict[str, object]) -> None:
    session.add(EntreeAudit(utilisateur_id=utilisateur_id, action=action, details=details))
    session.flush()


def verifier_identite(
    utilisateur_id: int, nom: str, email: str | None = None, telephone: str | None = None
) -> list[Conflit]:
    """Vérifie un nom avant d'ouvrir un dossier. Ouvre sa propre session, qui voit tout le cabinet."""
    with Session(get_engine()) as session, session.begin():
        conflits = verifier(
            session, Identite(nom=nom, email=email, telephone=telephone), _autorises(session, utilisateur_id)
        )
        _journaliser(
            session,
            utilisateur_id,
            "conflits_verification",
            {"nom": nom[:200], "conflits": len(conflits)},
        )
    return conflits


def conflits_du_dossier(utilisateur_id: int, reference: str) -> tuple[str, list[Conflit]]:
    """Vérifie toutes les parties adverses d'un dossier. Rend aussi l'intitulé du dossier."""
    with Session(get_engine()) as session, session.begin():
        dossier = session.scalars(select(Dossier).where(Dossier.reference == reference)).one_or_none()
        if dossier is None:
            raise LookupError(f"Dossier {reference} introuvable")
        autorises = _autorises(session, utilisateur_id)
        notre_client = session.scalars(select(Client.nom).where(Client.id == dossier.client_id)).one_or_none()
        parties = session.scalars(
            select(Partie).where(Partie.dossier_id == dossier.id, Partie.qualite.in_(QUALITES_OPPOSEES))
        ).all()
        conflits = [
            conflit
            for partie in parties
            for conflit in verifier(
                session,
                Identite(nom=partie.nom, email=partie.email, telephone=partie.telephone),
                autorises,
            )
            # Le client du dossier n'est évidemment pas en conflit avec lui-même.
            if conflit.client != notre_client
        ]
        _journaliser(
            session,
            utilisateur_id,
            "conflits_dossier",
            {"dossier": reference, "parties": len(parties), "conflits": len(conflits)},
        )
        return dossier.intitule, conflits


def balayer(utilisateur_id: int) -> list[tuple[str, Conflit]]:
    """Passe tout le cabinet en revue. Rend les conflits avec le dossier qui les porte."""
    with Session(get_engine()) as session, session.begin():
        autorises = _autorises(session, utilisateur_id)
        lignes = session.execute(
            select(Partie, Dossier.reference, Dossier.client_id)
            .join(Dossier, Partie.dossier_id == Dossier.id)
            .where(Partie.qualite.in_(QUALITES_OPPOSEES))
            .order_by(Dossier.reference)
        ).all()
        noms_clients = {client.id: client.nom for client in session.scalars(select(Client)).all()}
        resultats: list[tuple[str, Conflit]] = []
        for partie, reference, client_id in lignes:
            identite = Identite(nom=partie.nom, email=partie.email, telephone=partie.telephone)
            for conflit in verifier(session, identite, autorises):
                if conflit.client != noms_clients.get(client_id):
                    resultats.append((reference, conflit))
        _journaliser(
            session,
            utilisateur_id,
            "conflits_balayage",
            {"parties_examinees": len(lignes), "conflits": len(resultats)},
        )
        return resultats
