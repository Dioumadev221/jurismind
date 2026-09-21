"""Les pièces des dossiers et les échanges (emails, courriers, appels)."""

from datetime import date, datetime
from enum import StrEnum

from sqlalchemy import Column, DateTime, ForeignKey, String, Table, Text
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column, relationship

from jurismind.db.base import Base, Horodatage, enum_texte
from jurismind.db.models.metier import Dossier


class SensEchange(StrEnum):
    ENTRANT = "entrant"  # reçu par le cabinet
    SORTANT = "sortant"  # envoyé par le cabinet
    INTERNE = "interne"  # note interne


class Canal(StrEnum):
    EMAIL = "email"
    COURRIER = "courrier"
    TELEPHONE = "telephone"  # note prise après un appel


class StatutTraitement(StrEnum):
    """Où en est la lecture d'un document par JurisMind (OCR, découpage, vecteurs)."""

    A_TRAITER = "a_traiter"
    EN_COURS = "en_cours"
    TRAITE = "traite"
    ERREUR = "erreur"


# Table de liaison : quels documents sont joints à quelle communication.
# Elle remplace le champ COR_PJ de legacy, où les numéros étaient entassés dans du texte ("180;181").
pieces_jointes = Table(
    "pieces_jointes",
    Base.metadata,
    Column(
        "communication_id",
        ForeignKey("communications.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column("document_id", ForeignKey("documents.id", ondelete="CASCADE"), primary_key=True),
)


class Document(Base, Horodatage):
    __tablename__ = "documents"

    id: Mapped[int] = mapped_column(primary_key=True)
    external_id: Mapped[int | None] = mapped_column(unique=True)  # T_DOCUMENT.DOC_ID
    dossier_id: Mapped[int] = mapped_column(ForeignKey("dossiers.id"), index=True)
    titre: Mapped[str] = mapped_column(String(300))
    # Catégorie saisie dans legacy (parfois fausse ou « DIVERS »)…
    categorie_source: Mapped[str | None] = mapped_column(String(40))
    # … et catégorie déterminée par JurisMind en lisant le document.
    categorie_detectee: Mapped[str | None] = mapped_column(String(40))
    sens: Mapped[SensEchange] = mapped_column(enum_texte(SensEchange, "sens_document"))
    date_document: Mapped[date | None]
    auteur: Mapped[str | None] = mapped_column(String(200))
    # Emplacement du fichier sur le serveur de documents du cabinet.
    chemin_fichier: Mapped[str] = mapped_column(String(500))
    format: Mapped[str] = mapped_column(String(10))  # pdf, docx…
    # Empreinte du contenu du fichier : si elle change, le document a été modifié.
    empreinte_sha256: Mapped[str | None] = mapped_column(String(64))
    statut_traitement: Mapped[StatutTraitement] = mapped_column(
        enum_texte(StatutTraitement, "statut_traitement"),
        default=StatutTraitement.A_TRAITER,
    )
    ocr_utilise: Mapped[bool] = mapped_column(default=False)
    # Texte complet extrait du fichier (directement, ou par OCR pour les scans).
    texte: Mapped[str | None] = mapped_column(Text)

    dossier: Mapped[Dossier] = relationship()

    def __repr__(self) -> str:
        return f"<Document {self.titre!r}>"


class Communication(Base, Horodatage):
    __tablename__ = "communications"

    id: Mapped[int] = mapped_column(primary_key=True)
    external_id: Mapped[int | None] = mapped_column(unique=True)  # T_CORRESPONDANCE.COR_ID
    # Vide tant que l'email n'est pas rattaché à un dossier : c'est le travail de l'agent de tri.
    dossier_id: Mapped[int | None] = mapped_column(ForeignKey("dossiers.id"), index=True)
    canal: Mapped[Canal] = mapped_column(enum_texte(Canal, "canal"))
    sens: Mapped[SensEchange] = mapped_column(enum_texte(SensEchange, "sens_communication"))
    date_echange: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expediteur: Mapped[str] = mapped_column(String(255))
    destinataires: Mapped[list[str]] = mapped_column(ARRAY(String(255)), default=list)
    objet: Mapped[str | None] = mapped_column(String(300))
    corps: Mapped[str] = mapped_column(Text)

    dossier: Mapped[Dossier | None] = relationship()
    pieces_jointes: Mapped[list[Document]] = relationship(secondary=pieces_jointes)

    def __repr__(self) -> str:
        return f"<Communication {self.canal} {self.date_echange:%d/%m/%Y} {self.objet!r}>"
