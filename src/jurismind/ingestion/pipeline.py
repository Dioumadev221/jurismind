"""Chaîne d'ingestion : des fichiers du cabinet aux extraits interrogeables.

    fichier → texte (OCR si scan) → découpage → extraits → vecteurs

Deux principes de production :

- **On ne refait pas le travail déjà fait.** L'empreinte du fichier (SHA-256) dit s'il a
  changé ; l'OCR, qui coûte plusieurs secondes par page, n'est refait que si nécessaire.
- **Le calcul des vecteurs est séparé de la lecture.** Sur une machine sans carte graphique,
  vectoriser des milliers d'extraits prend du temps : c'est une tâche de fond, reprenable,
  qui ne doit pas bloquer le reste.
"""

from __future__ import annotations

import hashlib
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from jurismind.core.config import get_settings
from jurismind.db.models import Communication, Document, Extrait, StatutTraitement
from jurismind.db.session import get_engine
from jurismind.ingestion.decoupage import Morceau, decouper, decouper_texte
from jurismind.ingestion.lecture import OcrIndisponible, lire
from jurismind.llm import modele_embeddings

logger = logging.getLogger(__name__)

LOT_VECTEURS = 16  # nombre d'extraits envoyés d'un coup au modèle d'embeddings


@dataclass
class BilanIngestion:
    documents_lus: int = 0
    documents_ignores: int = 0  # déjà traités et inchangés
    documents_en_erreur: int = 0
    scans_ocr: int = 0
    scans_en_attente: int = 0  # scans laissés de côté faute d'OCR installé
    communications_lues: int = 0
    extraits_crees: int = 0
    vecteurs_calcules: int = 0
    secondes: float = 0.0
    erreurs: list[str] = field(default_factory=list)


def empreinte(chemin: Path) -> str:
    """SHA-256 du fichier, lu par blocs pour ne pas charger un scan entier en mémoire."""
    resume = hashlib.sha256()
    with chemin.open("rb") as fichier:
        while bloc := fichier.read(65536):
            resume.update(bloc)
    return resume.hexdigest()


def _remplacer_extraits(session: Session, document: Document, morceaux: list[Morceau]) -> int:
    """Les extraits d'un document sont recréés en bloc : ils n'ont de sens qu'ensemble."""
    session.execute(delete(Extrait).where(Extrait.document_id == document.id))
    for morceau in morceaux:
        session.add(
            Extrait(
                dossier_id=document.dossier_id,
                document_id=document.id,
                position=morceau.position,
                page=morceau.page,
                contenu=morceau.contenu,
                metadonnees={
                    "titre": document.titre,
                    "categorie": document.categorie_source,
                    "date": document.date_document.isoformat() if document.date_document else None,
                },
            )
        )
    return len(morceaux)


def ingerer_document(
    session: Session, document: Document, racine: Path, bilan: BilanIngestion, force: bool = False
) -> None:
    chemin = racine / document.chemin_fichier
    if not chemin.exists():
        logger.warning("Fichier absent : %s", chemin)
        document.statut_traitement = StatutTraitement.ERREUR
        bilan.documents_en_erreur += 1
        bilan.erreurs.append(f"{document.chemin_fichier} : fichier absent")
        return

    signature = empreinte(chemin)
    inchange = document.empreinte_sha256 == signature
    if inchange and document.statut_traitement is StatutTraitement.TRAITE and not force:
        bilan.documents_ignores += 1
        return

    document.statut_traitement = StatutTraitement.EN_COURS
    try:
        lecture = lire(chemin)
    except OcrIndisponible:
        # Sans Tesseract, le scan reste « à traiter » : une prochaine campagne le lira,
        # et tous les autres documents sont ingérés normalement.
        logger.warning("Scan laissé de côté faute d'OCR : %s", chemin.name)
        document.statut_traitement = StatutTraitement.A_TRAITER
        bilan.scans_en_attente += 1
        return
    except Exception as erreur:  # noqa: BLE001 - un fichier illisible ne doit pas tout arrêter
        logger.warning("Lecture impossible (%s) : %s", chemin.name, erreur)
        document.statut_traitement = StatutTraitement.ERREUR
        bilan.documents_en_erreur += 1
        bilan.erreurs.append(f"{document.chemin_fichier} : {erreur}")
        return

    document.texte = lecture.texte
    document.ocr_utilise = lecture.ocr
    document.empreinte_sha256 = signature
    document.statut_traitement = StatutTraitement.TRAITE
    bilan.documents_lus += 1
    bilan.scans_ocr += int(lecture.ocr)
    bilan.extraits_crees += _remplacer_extraits(session, document, decouper(lecture))


def ingerer_documents(
    session: Session, bilan: BilanIngestion, limite: int | None = None, force: bool = False
) -> None:
    racine = Path(get_settings().documents_dir)
    requete = select(Document).order_by(Document.id)
    if limite:
        requete = requete.limit(limite)
    for document in session.scalars(requete):
        ingerer_document(session, document, racine, bilan, force=force)
        session.flush()


def ingerer_communications(session: Session, bilan: BilanIngestion, force: bool = False) -> None:
    """Les emails et courriers sont déjà du texte : ils passent directement au découpage."""
    deja_decoupees = set(
        session.scalars(select(Extrait.communication_id).where(Extrait.communication_id.is_not(None)))
    )
    for communication in session.scalars(select(Communication).order_by(Communication.id)):
        if communication.id in deja_decoupees and not force:
            continue
        session.execute(delete(Extrait).where(Extrait.communication_id == communication.id))
        # L'objet est répété en tête : il porte souvent le nom de la partie adverse.
        texte = f"{communication.objet or ''}\n\n{communication.corps}".strip()
        for morceau in decouper_texte(texte):
            session.add(
                Extrait(
                    dossier_id=communication.dossier_id,
                    communication_id=communication.id,
                    position=morceau.position,
                    page=None,
                    contenu=morceau.contenu,
                    metadonnees={
                        "titre": communication.objet,
                        "categorie": f"{communication.canal}_{communication.sens}",
                        "date": communication.date_echange.date().isoformat(),
                        "expediteur": communication.expediteur,
                    },
                )
            )
            bilan.extraits_crees += 1
        bilan.communications_lues += 1
        session.flush()


def calculer_vecteurs(session: Session, bilan: BilanIngestion, limite: int | None = None) -> None:
    """Calcule les vecteurs manquants, par lots, en reprenant là où on s'était arrêté."""
    modele = modele_embeddings()
    restants = session.scalar(select(func.count()).select_from(Extrait).where(Extrait.embedding.is_(None)))
    logger.info("%s extraits à vectoriser", restants)

    traites = 0
    while limite is None or traites < limite:
        taille = LOT_VECTEURS if limite is None else min(LOT_VECTEURS, limite - traites)
        lot = list(
            session.scalars(
                select(Extrait).where(Extrait.embedding.is_(None)).order_by(Extrait.id).limit(taille)
            )
        )
        if not lot:
            return
        # Le titre du document est ajouté au texte envoyé au modèle : un extrait de
        # « Conclusions en réponse » n'a pas le même sens qu'un extrait de facture.
        textes = [f"{extrait.metadonnees.get('titre') or ''}\n{extrait.contenu}".strip() for extrait in lot]
        for extrait, vecteur in zip(lot, modele.embed_documents(textes), strict=True):
            extrait.embedding = vecteur
        session.flush()
        traites += len(lot)
        bilan.vecteurs_calcules += len(lot)
        logger.info("vecteurs : %s / %s", bilan.vecteurs_calcules, restants)


def ingerer(
    limite: int | None = None,
    force: bool = False,
    avec_vecteurs: bool = True,
    limite_vecteurs: int | None = None,
) -> BilanIngestion:
    """Lit les documents et les échanges, puis calcule les vecteurs manquants."""
    bilan = BilanIngestion()
    depart = time.perf_counter()
    with Session(get_engine()) as session, session.begin():
        ingerer_documents(session, bilan, limite=limite, force=force)
        ingerer_communications(session, bilan, force=force)
    if avec_vecteurs:
        with Session(get_engine()) as session, session.begin():
            calculer_vecteurs(session, bilan, limite=limite_vecteurs)
    bilan.secondes = time.perf_counter() - depart
    return bilan
