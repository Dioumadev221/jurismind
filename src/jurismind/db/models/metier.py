"""Les données métier du cabinet : clients, dossiers, et qui a le droit de voir quel dossier."""

from datetime import date
from enum import StrEnum

from sqlalchemy import BigInteger, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from jurismind.db.base import Base, Horodatage, enum_texte
from jurismind.db.models.utilisateur import Utilisateur


class TypeClient(StrEnum):
    SOCIETE = "societe"
    PARTICULIER = "particulier"


class TypeDossier(StrEnum):
    CONTENTIEUX = "contentieux"  # un procès
    CONSEIL = "conseil"  # du droit des affaires : contrats, sociétés…


class StatutDossier(StrEnum):
    EN_COURS = "en_cours"
    CLOS = "clos"
    ARCHIVE = "archive"


class QualitePartie(StrEnum):
    """Le rôle d'une personne extérieure au cabinet dans un dossier."""

    ADVERSE = "adverse"  # celui contre qui on agit
    AVOCAT_ADVERSE = "avocat_adverse"  # son avocat (le « confrère »)
    HUISSIER = "huissier"  # remet les actes et fait les saisies
    TIERS = "tiers"  # cocontractant, banque…


class Client(Base, Horodatage):
    __tablename__ = "clients"

    id: Mapped[int] = mapped_column(primary_key=True)
    # Identifiant du client dans le logiciel du cabinet (T_CLIENT.CLI_ID).
    external_id: Mapped[int | None] = mapped_column(unique=True)
    type: Mapped[TypeClient] = mapped_column(enum_texte(TypeClient, "type_client"))
    nom: Mapped[str] = mapped_column(String(200))
    forme_juridique: Mapped[str | None] = mapped_column(String(20))  # SARL, SA…
    rccm: Mapped[str | None] = mapped_column(String(40))
    ninea: Mapped[str | None] = mapped_column(String(20))
    adresse: Mapped[str | None] = mapped_column(String(250))
    ville: Mapped[str | None] = mapped_column(String(60))
    telephone: Mapped[str | None] = mapped_column(String(20))
    email: Mapped[str | None] = mapped_column(String(255))

    dossiers: Mapped[list["Dossier"]] = relationship(back_populates="client")
    contacts: Mapped[list["Contact"]] = relationship(back_populates="client", cascade="all, delete-orphan")

    def __repr__(self) -> str:
        return f"<Client {self.nom}>"


class Dossier(Base, Horodatage):
    __tablename__ = "dossiers"

    id: Mapped[int] = mapped_column(primary_key=True)
    # Identifiant du dossier dans le logiciel du cabinet (T_DOSSIER.DOS_ID).
    external_id: Mapped[int | None] = mapped_column(unique=True)
    reference: Mapped[str] = mapped_column(String(20), unique=True)  # ex. D2026-0024
    client_id: Mapped[int] = mapped_column(ForeignKey("clients.id"), index=True)
    intitule: Mapped[str] = mapped_column(String(300))
    type: Mapped[TypeDossier] = mapped_column(enum_texte(TypeDossier, "type_dossier"))
    matiere: Mapped[str] = mapped_column(String(30))  # recouvrement, bail, société…
    statut: Mapped[StatutDossier] = mapped_column(enum_texte(StatutDossier, "statut_dossier"))
    date_ouverture: Mapped[date]
    date_cloture: Mapped[date | None]
    juridiction: Mapped[str | None] = mapped_column(String(150))
    numero_rg: Mapped[str | None] = mapped_column(String(40))  # numéro de l'affaire au tribunal
    enjeu_fcfa: Mapped[int | None] = mapped_column(BigInteger)
    confidentiel: Mapped[bool] = mapped_column(default=False)

    client: Mapped[Client] = relationship(back_populates="dossiers")
    acces: Mapped[list["AccesDossier"]] = relationship(back_populates="dossier", cascade="all, delete-orphan")
    parties: Mapped[list["Partie"]] = relationship(back_populates="dossier", cascade="all, delete-orphan")

    def __repr__(self) -> str:
        return f"<Dossier {self.reference}>"


class AccesDossier(Base):
    """Qui peut voir quel dossier. C'est la base de toute l'isolation des données."""

    __tablename__ = "acces_dossiers"

    dossier_id: Mapped[int] = mapped_column(ForeignKey("dossiers.id", ondelete="CASCADE"), primary_key=True)
    utilisateur_id: Mapped[int] = mapped_column(
        ForeignKey("utilisateurs.id", ondelete="CASCADE"), primary_key=True, index=True
    )
    est_responsable: Mapped[bool] = mapped_column(default=False)

    dossier: Mapped[Dossier] = relationship(back_populates="acces")
    utilisateur: Mapped[Utilisateur] = relationship()


class Contact(Base, Horodatage):
    """Une personne qui travaille chez un client (gérant, directeur financier…)."""

    __tablename__ = "contacts"

    id: Mapped[int] = mapped_column(primary_key=True)
    external_id: Mapped[int | None] = mapped_column(unique=True)  # T_CONTACT.CT_ID
    client_id: Mapped[int] = mapped_column(ForeignKey("clients.id", ondelete="CASCADE"), index=True)
    prenom: Mapped[str | None] = mapped_column(String(60))
    nom: Mapped[str] = mapped_column(String(60))
    fonction: Mapped[str | None] = mapped_column(String(80))
    email: Mapped[str | None] = mapped_column(String(255), index=True)
    telephone: Mapped[str | None] = mapped_column(String(20))

    client: Mapped[Client] = relationship(back_populates="contacts")

    def __repr__(self) -> str:
        return f"<Contact {self.prenom} {self.nom}>"


class Partie(Base, Horodatage):
    """Une personne extérieure au cabinet impliquée dans un dossier."""

    __tablename__ = "parties"

    id: Mapped[int] = mapped_column(primary_key=True)
    external_id: Mapped[int | None] = mapped_column(unique=True)  # T_INTERVENANT.INT_ID
    dossier_id: Mapped[int] = mapped_column(ForeignKey("dossiers.id", ondelete="CASCADE"), index=True)
    qualite: Mapped[QualitePartie] = mapped_column(enum_texte(QualitePartie, "qualite_partie"))
    nom: Mapped[str] = mapped_column(String(200))
    adresse: Mapped[str | None] = mapped_column(String(250))
    email: Mapped[str | None] = mapped_column(String(255), index=True)
    telephone: Mapped[str | None] = mapped_column(String(20))

    dossier: Mapped[Dossier] = relationship(back_populates="parties")

    def __repr__(self) -> str:
        return f"<Partie {self.qualite} : {self.nom}>"
