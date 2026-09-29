"""Recherche hybride dans les extraits du cabinet.

Deux recherches complémentaires, lancées sur la même question :

- **par le sens** (vecteurs pgvector) : retrouve « délai pour contester » dans un texte qui
  parle d'« opposition à l'ordonnance », sans mot commun ;
- **par les mots** (plein texte français) : retrouve « FA-2025-978 » ou « RG n° 4832/2024 »,
  que les vecteurs situent mal car un numéro n'a pas de sens propre.

Les deux listes sont fusionnées par la méthode RRF (*Reciprocal Rank Fusion*) : chaque
extrait marque des points selon son **rang** dans chaque liste, ce qui évite de comparer
des scores incomparables (une distance cosinus et un score BM25 ne vivent pas sur la même
échelle).

Le filtrage des droits n'est pas fait ici : il est appliqué par PostgreSQL lui-même, grâce
à la session ouverte au nom de l'utilisateur (`session_utilisateur`). Un extrait interdit
n'est donc jamais lu, et ne peut pas arriver jusqu'au modèle.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from sqlalchemy import Select, func, or_, select
from sqlalchemy.orm import Session

from jurismind.core.texte import references_brutes
from jurismind.db.models import Communication, Document, Dossier, Extrait
from jurismind.llm import modele_embeddings

logger = logging.getLogger(__name__)

# Nombre d'extraits demandés à chacune des deux recherches avant fusion.
CANDIDATS = 30
# Constante de la fusion RRF : amortit l'écart entre les premiers rangs.
LISSAGE_RRF = 60
# Une référence exacte (« FA-2025-978 ») demandée dans la question pèse plus lourd : c'est
# une correspondance certaine, là où le sens et les mots ne donnent qu'une probabilité.
POIDS_REFERENCE = 2.0


@dataclass
class Filtres:
    """Restreint la recherche. Les droits, eux, sont appliqués par la base."""

    dossier_id: int | None = None
    client_id: int | None = None
    categories: list[str] = field(default_factory=list)
    depuis: date | None = None
    jusqu_a: date | None = None


@dataclass
class Resultat:
    """Un extrait retrouvé, avec de quoi le citer."""

    extrait: Extrait
    score: float
    rang_vectoriel: int | None = None
    rang_plein_texte: int | None = None
    par_reference: bool = False
    # Proximité de sens avec la question, entre 0 et 1 (vide si trouvé par les seuls mots).
    similarite: float | None = None

    @property
    def titre(self) -> str:
        source = self.extrait.document or self.extrait.communication
        if isinstance(source, Document):
            return source.titre
        if isinstance(source, Communication):
            return source.objet or f"Échange du {source.date_echange:%d/%m/%Y}"
        return "Source inconnue"

    @property
    def reference(self) -> str:
        """Référence lisible pour une citation : « Jugement…, page 2 »."""
        page = f", page {self.extrait.page}" if self.extrait.page else ""
        return f"{self.titre}{page}"

    @property
    def trouve_par(self) -> str:
        pistes = []
        if self.par_reference:
            pistes.append("référence")
        if self.rang_vectoriel is not None:
            pistes.append("sens")
        if self.rang_plein_texte is not None:
            pistes.append("mots")
        return " + ".join(pistes)


def _appliquer_filtres(requete: Select[Any], filtres: Filtres) -> Select[Any]:
    """Restreint la recherche au périmètre demandé (un dossier, un client, une période…)."""
    if filtres.dossier_id is not None:
        requete = requete.where(Extrait.dossier_id == filtres.dossier_id)

    if filtres.client_id is not None:
        dossiers_du_client = select(Dossier.id).where(Dossier.client_id == filtres.client_id)
        requete = requete.where(Extrait.dossier_id.in_(dossiers_du_client))

    if filtres.categories:
        requete = requete.where(Extrait.document.has(Document.categorie_source.in_(filtres.categories)))

    # Un extrait vient d'un document (daté `date_document`) ou d'un échange (`date_echange`).
    if filtres.depuis is not None:
        requete = requete.where(
            or_(
                Extrait.document.has(Document.date_document >= filtres.depuis),
                Extrait.communication.has(Communication.date_echange >= filtres.depuis),
            )
        )
    if filtres.jusqu_a is not None:
        requete = requete.where(
            or_(
                Extrait.document.has(Document.date_document <= filtres.jusqu_a),
                Extrait.communication.has(Communication.date_echange <= filtres.jusqu_a),
            )
        )
    return requete


def recherche_vectorielle(
    session: Session, vecteur: list[float], filtres: Filtres, limite: int = CANDIDATS
) -> list[tuple[Extrait, float]]:
    """Extraits les plus proches par le sens, avec leur similarité (1 = identique)."""
    distance = Extrait.embedding.cosine_distance(vecteur).label("distance")
    requete = _appliquer_filtres(select(Extrait, distance).where(Extrait.embedding.is_not(None)), filtres)
    lignes = session.execute(requete.order_by(distance).limit(limite)).all()
    return [(extrait, 1 - float(ecart)) for extrait, ecart in lignes]


def recherche_plein_texte(
    session: Session, question: str, filtres: Filtres, limite: int = CANDIDATS
) -> list[Extrait]:
    # `websearch_to_tsquery` accepte la façon d'écrire des utilisateurs : guillemets,
    # « ou », mots isolés — sans planter sur une apostrophe ou un tiret.
    requete_texte = func.websearch_to_tsquery("french", question)
    pertinence = func.ts_rank_cd(Extrait.recherche_texte, requete_texte)
    requete = _appliquer_filtres(
        select(Extrait).where(Extrait.recherche_texte.op("@@")(requete_texte)), filtres
    )
    return list(session.scalars(requete.order_by(pertinence.desc()).limit(limite)))


def recherche_par_reference(
    session: Session, question: str, filtres: Filtres, limite: int = CANDIDATS
) -> list[Extrait]:
    """Extraits contenant littéralement une référence citée dans la question.

    Sur un scan, l'OCR détruit parfois le numéro dans le corps du document (« FACTURE N4 ») :
    le titre, issu du logiciel du cabinet, est donc cherché lui aussi.
    """
    references = references_brutes(question)
    if not references:
        return []
    conditions = [
        or_(
            Extrait.contenu.ilike(f"%{reference}%"),
            Extrait.metadonnees["titre"].astext.ilike(f"%{reference}%"),
        )
        for reference in references
    ]
    requete = _appliquer_filtres(select(Extrait).where(or_(*conditions)), filtres)
    return list(session.scalars(requete.limit(limite)))


def fusionner(
    vectoriels: list[tuple[Extrait, float]],
    textuels: list[Extrait],
    limite: int,
    references: list[Extrait] | None = None,
) -> list[Resultat]:
    """Fusion RRF : chaque liste vote selon les rangs, pas selon des scores incomparables."""
    scores: dict[int, float] = {}
    rangs: dict[int, dict[str, int]] = {}
    similarites: dict[int, float] = {}
    for rang, (extrait, similarite) in enumerate(vectoriels, start=1):
        scores[extrait.id] = scores.get(extrait.id, 0.0) + 1 / (LISSAGE_RRF + rang)
        rangs.setdefault(extrait.id, {})["vectoriel"] = rang
        similarites[extrait.id] = similarite
    for rang, extrait in enumerate(textuels, start=1):
        scores[extrait.id] = scores.get(extrait.id, 0.0) + 1 / (LISSAGE_RRF + rang)
        rangs.setdefault(extrait.id, {})["plein_texte"] = rang
    for rang, extrait in enumerate(references or [], start=1):
        scores[extrait.id] = scores.get(extrait.id, 0.0) + POIDS_REFERENCE / (LISSAGE_RRF + rang)
        rangs.setdefault(extrait.id, {})["reference"] = rang

    connus = (
        {extrait.id: extrait for extrait, _ in vectoriels}
        | {e.id: e for e in textuels}
        | {e.id: e for e in references or []}
    )
    meilleurs = sorted(scores, key=lambda identifiant: scores[identifiant], reverse=True)[:limite]
    return [
        Resultat(
            extrait=connus[identifiant],
            score=scores[identifiant],
            rang_vectoriel=rangs[identifiant].get("vectoriel"),
            rang_plein_texte=rangs[identifiant].get("plein_texte"),
            par_reference="reference" in rangs[identifiant],
            similarite=similarites.get(identifiant),
        )
        for identifiant in meilleurs
    ]


def rechercher(
    session: Session,
    question: str,
    filtres: Filtres | None = None,
    limite: int = 5,
    vecteur: list[float] | None = None,
) -> list[Resultat]:
    """Recherche hybride, dans les seuls dossiers visibles par la session en cours."""
    filtres = filtres or Filtres()
    vecteur = vecteur if vecteur is not None else modele_embeddings().embed_query(question)

    vectoriels = recherche_vectorielle(session, vecteur, filtres)
    textuels = recherche_plein_texte(session, question, filtres)
    references = recherche_par_reference(session, question, filtres)
    logger.debug(
        "candidats : %s par le sens, %s par les mots, %s par référence",
        len(vectoriels),
        len(textuels),
        len(references),
    )
    return fusionner(vectoriels, textuels, limite, references=references)
