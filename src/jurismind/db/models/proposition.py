"""Ce que l'IA propose de faire, et qui l'a autorisé.

Une proposition n'est pas une action : c'est une demande d'autorisation. Rattacher un email
au mauvais dossier, envoyer une relance à un client qui a déjà payé, créer une tâche sur le
mauvais compte — ces gestes se voient de l'extérieur du cabinet et ne se reprennent pas.
Ils ne sont donc produits qu'après qu'un humain a dit oui, et la ligne garde qui a dit oui.

On distingue **validée** (un humain a tranché) de **appliquée** (l'effet est produit) :
créer une tâche dans le CRM passe par le réseau et peut échouer. Une proposition validée
dont l'application a échoué reste rejouable, elle n'est pas perdue.
"""

from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import DateTime, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from jurismind.db.base import Base, Horodatage, enum_texte
from jurismind.db.models.documents import Communication
from jurismind.db.models.metier import Client
from jurismind.db.models.utilisateur import Utilisateur


class TypeProposition(StrEnum):
    RATTACHEMENT = "rattachement"  # rattacher un échange à un dossier
    BROUILLON = "brouillon"  # réponse ou relance à relire avant envoi
    TACHE_CRM = "tache_crm"  # tâche de suivi à créer dans le CRM


class StatutProposition(StrEnum):
    PROPOSEE = "proposee"  # l'IA a proposé, personne n'a encore tranché
    VALIDEE = "validee"  # un humain a dit oui, l'effet n'est pas encore produit
    APPLIQUEE = "appliquee"  # l'effet est produit (dossier rattaché, tâche créée)
    REJETEE = "rejetee"  # un humain a dit non
    ECHOUEE = "echouee"  # validée, mais l'application a échoué : à rejouer


class Confiance(StrEnum):
    """Force de l'indice qui a conduit à la proposition (cf. `agents/indices.py`)."""

    HAUTE = "haute"
    MOYENNE = "moyenne"
    FAIBLE = "faible"


class Proposition(Base, Horodatage):
    __tablename__ = "propositions"

    id: Mapped[int] = mapped_column(primary_key=True)
    type: Mapped[TypeProposition] = mapped_column(enum_texte(TypeProposition, "type_proposition"))
    statut: Mapped[StatutProposition] = mapped_column(
        enum_texte(StatutProposition, "statut_proposition"),
        default=StatutProposition.PROPOSEE,
        index=True,
    )
    # L'échange à l'origine de la proposition, quand il y en a un.
    communication_id: Mapped[int | None] = mapped_column(
        ForeignKey("communications.id", ondelete="CASCADE"), index=True
    )
    # Dossier visé. C'est aussi ce qui porte l'isolation : une proposition de rattachement
    # n'est visible que de ceux qui voient le dossier proposé.
    dossier_id: Mapped[int | None] = mapped_column(ForeignKey("dossiers.id"), index=True)
    client_id: Mapped[int | None] = mapped_column(ForeignKey("clients.id"))
    titre: Mapped[str] = mapped_column(String(300))
    contenu: Mapped[str | None] = mapped_column(Text)  # le brouillon, le libellé de la tâche
    # Pourquoi cette proposition : l'indice, nommé, qui y a conduit. Jamais vide.
    justification: Mapped[str] = mapped_column(String(500))
    confiance: Mapped[Confiance] = mapped_column(enum_texte(Confiance, "confiance_proposition"))
    # Priorité, candidats écartés, identifiant rendu par le CRM…
    donnees: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    decide_par_id: Mapped[int | None] = mapped_column(ForeignKey("utilisateurs.id"))
    decide_le: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    erreur: Mapped[str | None] = mapped_column(Text)

    communication: Mapped[Communication | None] = relationship()
    client: Mapped[Client | None] = relationship()
    decide_par: Mapped[Utilisateur | None] = relationship()

    @property
    def tranchee(self) -> bool:
        """Un humain s'est-il prononcé ?"""
        return self.statut is not StatutProposition.PROPOSEE

    def __repr__(self) -> str:
        return f"<Proposition {self.type} {self.titre!r} ({self.statut})>"
