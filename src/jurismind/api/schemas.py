"""Ce que l'API reçoit et ce qu'elle rend.

Ces modèles ne servent pas qu'à valider : ils **sont** la documentation OpenAPI que le
cabinet lira. Chaque champ porte donc une description, et les exemples sont ceux du vrai
corpus, pas des « foo » et des « bar ».
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, Field

from jurismind.db.models import Confiance, Role, StatutProposition, TypeProposition

# --------------------------------------------------------------------------- connexion


class DemandeConnexion(BaseModel):
    email: str = Field(description="Adresse du compte", examples=["m.dieng@teranga-avocats.example"])
    mot_de_passe: str = Field(description="Mot de passe du compte")


class UtilisateurPublic(BaseModel):
    id: int
    email: str
    nom_complet: str
    role: Role = Field(description="admin, avocat ou assistant")


class Jeton(BaseModel):
    jeton: str = Field(description="À placer dans l'en-tête `Authorization: Bearer …`")
    type_jeton: str = "bearer"
    expire_dans: int = Field(description="Durée de vie restante, en secondes")
    utilisateur: UtilisateurPublic


# --------------------------------------------------------------------------- recherche (F3)


class Filtre(BaseModel):
    """Restreint la recherche. Les droits, eux, sont appliqués par la base."""

    dossier_id: int | None = None
    client_id: int | None = None
    categories: list[str] = Field(default_factory=list, examples=[["FACTURE", "MISE_EN_DEMEURE"]])
    depuis: date | None = None
    jusqu_a: date | None = None


class DemandeRecherche(BaseModel):
    texte: str = Field(description="Ce qu'on cherche", examples=["délai d'opposition"])
    filtres: Filtre = Field(default_factory=Filtre)
    limite: int = Field(default=8, ge=1, le=50)


class ResultatRecherche(BaseModel):
    extrait_id: int
    reference: str = Field(description="De quelle pièce vient l'extrait, et à quelle page")
    contenu: str
    score: float = Field(description="Score de fusion RRF des trois voies de recherche")
    similarite: float | None = Field(
        default=None, description="Proximité vectorielle, si cette voie l'a trouvé"
    )
    trouve_par: str = Field(description="Voies qui l'ont remonté", examples=["sens + mots"])
    dossier_id: int | None = None


# --------------------------------------------------------------- réponses citées (F2, F11)


class DemandeQuestion(BaseModel):
    question: str = Field(examples=["Quel délai le débiteur a-t-il pour former opposition ?"])
    filtres: Filtre = Field(default_factory=Filtre)


class Citation(BaseModel):
    numero: int
    reference: str
    extrait_id: int
    dossier_id: int | None = None
    similarite: float | None = None


class ReponseCitee(BaseModel):
    texte: str
    citations: list[Citation] = Field(description="Sources réellement utilisées, vérifiées par le code")
    abstention: bool = Field(description="Vrai quand les pièces ne permettent pas de répondre")
    secondes: float
    sources_examinees: int


# --------------------------------------------------------------------------- agents (F6 à F9)


class DemandeAgent(BaseModel):
    demande: str = Field(
        default="",
        description="Question ou consigne en langage naturel ; vide pour une synthèse",
        examples=["chronologie", "points d'attention", "Le débiteur a-t-il formé opposition ?"],
    )


class ReponseAgentPublique(BaseModel):
    intention: str = Field(description="Ce que l'agent a compris de la demande")
    texte: str
    citations: list[dict[str, Any]] = Field(default_factory=list)
    donnees: dict[str, Any] = Field(
        default_factory=dict, description="Les faits structurés derrière la réponse"
    )
    abstention: bool
    secondes: float


# --------------------------------------------------------------------------- dossiers, clients


class DossierPublic(BaseModel):
    id: int
    reference: str
    intitule: str
    type: str
    matiere: str
    statut: str
    date_ouverture: date
    date_cloture: date | None = None
    juridiction: str | None = None
    enjeu_fcfa: int | None = None
    responsable: str | None = None
    derniere_activite: date | None = None


class EvenementPublic(BaseModel):
    date: date
    type: str = Field(description="document, echange ou etape")
    libelle: str
    detail: str | None = None
    document_id: int | None = None
    communication_id: int | None = None


class PointAttentionPublic(BaseModel):
    gravite: str = Field(description="haute ou moyenne")
    libelle: str
    detail: str = Field(description="La date, le montant ou le statut qui a déclenché la règle")
    dossier: str | None = None


class DocumentPublic(BaseModel):
    id: int
    titre: str
    dossier: str | None = None
    categorie_source: str | None = Field(default=None, description="Catégorie saisie par le cabinet")
    categorie_detectee: str | None = Field(default=None, description="Catégorie reconnue par JurisMind")
    date_document: date | None = None
    format: str | None = None
    lu_par_ocr: bool = False
    caracteres: int = 0


# --------------------------------------------------------------------------- courrier (F9)


class PropositionPublique(BaseModel):
    """Un geste que l'IA suggère, en attente d'un oui ou d'un non."""

    id: int
    type: TypeProposition
    statut: StatutProposition
    titre: str
    justification: str = Field(description="L'indice qui a conduit à la proposition. Jamais vide.")
    confiance: Confiance
    dossier_id: int | None = None
    contenu: str | None = Field(default=None, description="Le brouillon, ou le libellé de la tâche")
    decide_par_id: int | None = None
    decide_le: datetime | None = None
    erreur: str | None = Field(default=None, description="Pourquoi l'application a échoué, le cas échéant")
    donnees: dict[str, Any] = Field(default_factory=dict)


class DemandeRejet(BaseModel):
    motif: str = Field(default="", description="Conservé au journal, pour qu'on sache pourquoi")


class DemandeTri(BaseModel):
    limite: int = Field(default=20, ge=1, le=100, description="Nombre d'emails à examiner")


# --------------------------------------------------------------------------- divers


class Sante(BaseModel):
    statut: str
    base: bool = Field(description="PostgreSQL répond")
    modeles: str = Field(description="Fournisseur de modèles configuré")


class Erreur(BaseModel):
    detail: str
