from enum import StrEnum

from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from jurismind.db.base import Base, Horodatage, enum_texte


class Role(StrEnum):
    ADMIN = "admin"  # gére les comptes et les connecteurs, ne lit pas le contenu des dociers
    AVOCAT = "avocat"  # associé, collaborateurs et juristes
    ASSISTANT = "assistant"  # secretaire juridique, sans accées aus docier confidentiels


class Utilisateur(Base, Horodatage):
    __tablename__ = "utilisateurs"
    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True)
    nom_complet: Mapped[str] = mapped_column(String(150))
    # Jamais le mot de passe lui-même : seulement son empreinte (hash).
    mot_de_passe_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[Role] = mapped_column(enum_texte(Role, "role"))
    actif: Mapped[bool] = mapped_column(default=True)
    # Identifiant de la personne dans le logiciel du cabinet (T_AVOCAT.AV_ID), s'il existe.
    external_id: Mapped[int | None] = mapped_column(unique=True)

    def __repr__(self) -> str:
        return f"<Utilisateur {self.email} ({self.role})>"
