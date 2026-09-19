"""Le « monde » simulé du cabinet, dans sa version propre (vérité de référence).

Ce modèle sert de source unique : la base legacy, le CRM et les fichiers en sont
dérivés (avec des imperfections ajoutées), et le jeu d'évaluation s'appuie sur
lui comme corrigé.
"""

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any


@dataclass
class Avocat:
    id: int
    initiales: str
    prenom: str
    nom: str
    email: str
    fonction: str  # ASSOCIE | COLLAB | JURISTE | ASSIST

    @property
    def nom_complet(self) -> str:
        return f"{self.prenom} {self.nom}"

    @property
    def titre(self) -> str:
        return f"Me {self.nom_complet}" if self.fonction in ("ASSOCIE", "COLLAB") else self.nom_complet


@dataclass
class Contact:
    id: int
    client_id: int
    prenom: str
    nom: str
    fonction: str
    email: str
    telephone: str

    @property
    def nom_complet(self) -> str:
        return f"{self.prenom} {self.nom}"


@dataclass
class Client:
    id: int
    code: str
    type: str  # PM (personne morale) | PP (personne physique)
    nom: str  # raison sociale ou « Prénom Nom »
    forme: str | None
    secteur: str | None
    rccm: str | None
    ninea: str | None
    adresse: str
    ville: str
    telephone: str
    email: str
    domaine: str | None
    date_creation: date
    contacts: list[Contact] = field(default_factory=list)

    @property
    def interlocuteur(self) -> Contact:
        return self.contacts[0]


@dataclass
class Partie:
    qualite: str  # ADV | AVADV | HUIS | TIERS
    nom: str
    adresse: str | None = None
    email: str | None = None
    telephone: str | None = None


@dataclass
class Document:
    id: int
    dossier_id: int
    categorie: str
    libelle: str
    date: date
    sens: str  # E (entrant) | S (sortant) | I (interne)
    auteur: str
    fichier: str
    format: str  # pdf | docx
    scan: bool
    faits: dict[str, Any] = field(default_factory=dict)


@dataclass
class Correspondance:
    id: int
    dossier_id: int | None
    type: str  # MAIL | COURRIER | TEL
    sens: str  # E | S
    date: datetime
    expediteur: str
    destinataires: list[str]
    objet: str
    corps: str
    pieces_jointes: list[int] = field(default_factory=list)
    classee: bool = True  # False : pas encore rattachée au dossier (à trier)


@dataclass
class Dossier:
    id: int
    numero: str
    client_id: int
    intitule: str
    type: str  # CTX (contentieux) | CSL (conseil / affaires)
    matiere: str
    statut: str  # EC (en cours) | CL (clos) | AR (archivé)
    date_ouverture: date
    date_cloture: date | None
    juridiction: str | None
    numero_rg: str | None
    enjeu: int | None  # FCFA
    confidentiel: bool
    responsable_id: int
    equipe_ids: list[int]
    parties: list[Partie] = field(default_factory=list)
    documents: list[Document] = field(default_factory=list)
    correspondances: list[Correspondance] = field(default_factory=list)
    faits: dict[str, Any] = field(default_factory=dict)


@dataclass
class Monde:
    reference: date
    avocats: list[Avocat]
    clients: list[Client]
    dossiers: list[Dossier]
    correspondances_hors_dossier: list[Correspondance]
    crm: dict[str, Any]
