"""La chaîne d'ingestion : lire les fichiers du cabinet, les découper, les vectoriser."""

from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from jurismind.connectors.legacy import synchroniser
from jurismind.db.models import Document, Extrait, StatutTraitement
from jurismind.db.session import get_engine
from jurismind.ingestion.decoupage import TAILLE_MAXIMALE, decouper, decouper_page, decouper_texte
from jurismind.ingestion.lecture import Lecture, Page, lire
from jurismind.ingestion.pipeline import BilanIngestion, empreinte, ingerer

DOCUMENTS = Path("data/cabinet/documents")


def un_fichier(motif: str) -> Path:
    fichier = next(DOCUMENTS.rglob(motif), None)
    if fichier is None:
        pytest.skip(f"aucun fichier {motif} : lancer `python -m simulation`")
    return fichier


# --------------------------------------------------------------------- lecture


def test_un_document_word_est_lu_avec_ses_tableaux() -> None:
    lecture = lire(un_fichier("*PROJET_STATUTS*.docx"))
    assert not lecture.ocr
    assert "STATUTS" in lecture.texte.upper()
    # La répartition du capital est dans un tableau : sans lui, les parts seraient perdues.
    assert "|" in lecture.texte


def test_un_pdf_texte_est_lu_page_par_page() -> None:
    lecture = lire(un_fichier("*ORDONNANCE_IP*.pdf"), ocr_si_necessaire=False)
    if lecture.vide:
        pytest.skip("ce fichier est un scan")
    assert lecture.pages[0].numero == 1
    assert len(lecture.texte) > 200


def test_un_scan_ne_rend_aucun_texte_sans_ocr() -> None:
    scans = [
        chemin
        for chemin in list(DOCUMENTS.rglob("*PV_SIGNIFICATION*.pdf"))[:12]
        if lire(chemin, ocr_si_necessaire=False).vide
    ]
    assert scans, "la simulation doit contenir des scans, sinon l'OCR n'est jamais éprouvé"


def test_un_format_inconnu_est_refuse(tmp_path: Path) -> None:
    fichier = tmp_path / "note.txt"
    fichier.write_text("bonjour")
    with pytest.raises(ValueError, match="Format non pris en charge"):
        lire(fichier)


def test_l_empreinte_change_avec_le_contenu(tmp_path: Path) -> None:
    fichier = tmp_path / "acte.pdf"
    fichier.write_bytes(b"contenu")
    premiere = empreinte(fichier)
    fichier.write_bytes(b"contenu modifie")
    assert premiere != empreinte(fichier)


# --------------------------------------------------------------------- découpage


def test_un_texte_court_reste_en_un_seul_extrait() -> None:
    lecture = Lecture(pages=[Page(numero=1, texte="Mise en demeure.\n\nVeuillez régler la somme due.")])
    morceaux = decouper(lecture)
    assert len(morceaux) == 1
    assert morceaux[0].page == 1 and morceaux[0].position == 0


def test_un_long_document_est_coupe_entre_les_articles() -> None:
    articles = "\n\n".join(f"Article {n} – " + "obligation contractuelle. " * 12 for n in range(1, 12))
    morceaux = decouper_page(Page(numero=1, texte=articles))
    assert len(morceaux) > 1
    assert all(len(m) <= TAILLE_MAXIMALE for m in morceaux)
    assert all(m.strip().startswith(("Article", "obligation")) for m in morceaux)


def test_les_extraits_se_chevauchent_pour_ne_rien_perdre() -> None:
    texte = " ".join(f"Phrase numéro {n} sur le recouvrement de la créance." for n in range(1, 60))
    morceaux = decouper_page(Page(numero=1, texte=texte))
    assert len(morceaux) > 1
    fin_du_premier = morceaux[0][-60:]
    assert any(mot in morceaux[1] for mot in fin_du_premier.split()[:4])


def test_les_pages_sont_conservees_pour_les_citations() -> None:
    lecture = Lecture(pages=[Page(1, "Première page." * 10), Page(2, "Seconde page." * 10)])
    pages = {morceau.page for morceau in decouper(lecture)}
    assert pages == {1, 2}


def test_un_email_est_decoupe_sans_pagination() -> None:
    morceaux = decouper_texte("Impayés\n\nMaître, veuillez engager le recouvrement.")
    assert len(morceaux) == 1 and morceaux[0].page is None


# --------------------------------------------------------------------- chaîne complète


class EmbeddingsFactices:
    """Évite d'appeler Ollama dans les tests : les vecteurs réels sont mesurés ailleurs."""

    def embed_documents(self, textes: list[str]) -> list[list[float]]:
        return [[float(len(texte) % 10)] * 1024 for texte in textes]


@pytest.fixture
def cabinet_synchronise(monkeypatch: pytest.MonkeyPatch) -> None:
    tables = (
        "journal_audit, taches, extraits, pieces_jointes, communications, documents, parties, "
        "acces_dossiers, dossiers, contacts, elements_crm, alias_clients, clients, utilisateurs"
    )
    with Session(get_engine()) as session, session.begin():
        session.execute(text(f"TRUNCATE {tables} RESTART IDENTITY CASCADE"))
    synchroniser(cible=get_engine())
    monkeypatch.setattr("jurismind.ingestion.pipeline.modele_embeddings", lambda: EmbeddingsFactices())


@pytest.mark.usefixtures("cabinet_synchronise")
def test_l_ingestion_produit_des_extraits_vectorises() -> None:
    bilan = ingerer(limite=8, limite_vecteurs=12)

    assert bilan.documents_lus + bilan.scans_en_attente == 8
    assert bilan.extraits_crees > 0
    assert bilan.vecteurs_calcules == 12

    with Session(get_engine()) as session:
        extrait = session.scalars(select(Extrait).where(Extrait.embedding.is_not(None))).first()
        assert extrait is not None
        assert extrait.embedding is not None
        assert len(extrait.embedding) == 1024
        assert extrait.dossier_id is not None, "sans dossier, l'extrait échapperait aux droits d'accès"
        assert extrait.metadonnees["titre"]


@pytest.mark.usefixtures("cabinet_synchronise")
def test_un_document_inchange_nest_pas_relu() -> None:
    premier = ingerer(limite=5, avec_vecteurs=False)
    second = ingerer(limite=5, avec_vecteurs=False)

    assert premier.documents_lus > 0
    assert second.documents_lus == 0
    assert second.documents_ignores == premier.documents_lus
    assert second.extraits_crees == 0


@pytest.mark.usefixtures("cabinet_synchronise")
def test_un_fichier_absent_est_signale_sans_arreter_la_campagne() -> None:
    with Session(get_engine()) as session, session.begin():
        document = session.scalars(select(Document).order_by(Document.id)).first()
        assert document is not None
        document.chemin_fichier = "D2026-0000/inexistant.pdf"

    bilan = ingerer(limite=5, avec_vecteurs=False)

    assert bilan.documents_en_erreur == 1
    assert bilan.documents_lus >= 1, "les autres documents doivent être lus malgré l'erreur"
    with Session(get_engine()) as session:
        en_erreur = session.scalar(
            select(func.count())
            .select_from(Document)
            .where(Document.statut_traitement == StatutTraitement.ERREUR)
        )
        assert en_erreur is not None
    assert en_erreur == 1


@pytest.mark.usefixtures("cabinet_synchronise")
def test_les_echanges_du_cabinet_sont_aussi_indexes() -> None:
    bilan: BilanIngestion = ingerer(limite=1, avec_vecteurs=False)

    assert bilan.communications_lues > 0
    with Session(get_engine()) as session:
        depuis_echanges = session.scalar(
            select(func.count()).select_from(Extrait).where(Extrait.communication_id.is_not(None))
        )
        sans_dossier = session.scalar(
            select(func.count())
            .select_from(Extrait)
            .where(Extrait.communication_id.is_not(None), Extrait.dossier_id.is_(None))
        )
        assert depuis_echanges is not None and sans_dossier is not None
    assert depuis_echanges > 0
    # Les emails pas encore classés n'ont pas de dossier : ils restent visibles pour le tri.
    assert sans_dossier > 0


def _extraits_du_document(session: Session, document_id: int) -> list[Extrait]:
    return list(session.scalars(select(Extrait).where(Extrait.document_id == document_id)))


@pytest.mark.usefixtures("cabinet_synchronise")
def test_relire_un_document_remplace_ses_extraits_sans_les_dupliquer() -> None:
    ingerer(limite=3, avec_vecteurs=False)
    with Session(get_engine()) as session:
        document = session.scalars(select(Document).order_by(Document.id)).first()
        assert document is not None
        avant = len(_extraits_du_document(session, document.id))

    ingerer(limite=3, avec_vecteurs=False, force=True)

    with Session(get_engine()) as session:
        apres = len(_extraits_du_document(session, document.id))
    assert avant == apres


def test_le_decoupage_ne_perd_pas_les_montants() -> None:
    texte = (
        "Nous vous mettons en demeure de régler la somme de 13 750 000 FCFA au titre des factures "
        "FA-2025-978, FA-2025-143 et FA-2026-988, dans un délai de 8 jours."
    )
    morceaux = decouper_texte(texte)
    reconstitue = " ".join(m.contenu for m in morceaux)
    for information in ("13 750 000", "FA-2025-978", "8 jours"):
        assert information in reconstitue


@pytest.mark.usefixtures("cabinet_synchronise")
def test_le_texte_complet_est_conserve_pour_les_traitements_suivants() -> None:
    ingerer(limite=4, avec_vecteurs=False)
    with Session(get_engine()) as session:
        documents: Any = session.scalars(
            select(Document).where(Document.statut_traitement == StatutTraitement.TRAITE)
        ).all()
    assert documents
    for document in documents:
        assert document.texte, "le texte extrait évite de refaire l'OCR à chaque analyse"
        assert document.empreinte_sha256
