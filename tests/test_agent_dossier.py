"""L'agent d'assistance sur un dossier : aiguillage, faits non inventés, droits respectés.

Le modèle est simulé. Ce qu'on vérifie ici, ce n'est pas la qualité d'Ollama (mesurée par le
jeu d'évaluation), c'est que le graphe se comporte comme on l'a conçu : il ne dérange pas le
modèle pour rien, il construit la chronologie lui-même, il refuse un chiffre qui ne vient pas
des pièces, et il ne laisse rien filtrer d'un dossier auquel l'utilisateur n'a pas accès.
"""

import json
from datetime import UTC, date, datetime
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from jurismind.agents.dossier import Intention, assister, deviner_intention
from jurismind.agents.outils import evenements_du_dossier, fiche_dossier
from jurismind.db.models import (
    Canal,
    Communication,
    Document,
    Dossier,
    EntreeAudit,
    Extrait,
    SensEchange,
)
from jurismind.db.session import get_engine, session_utilisateur
from jurismind.rag.reponse import Citation, Reponse
from tests.conftest import Cabinet

DIMENSION = 1024


class ModeleSimule:
    """Renvoie la réponse choisie par le test, et note ce qu'on lui a demandé."""

    def __init__(self, reponse: Any) -> None:
        self.reponse = reponse if isinstance(reponse, str) else json.dumps(reponse)
        self.invites: list[str] = []

    def invoke(self, invite: str) -> Any:
        self.invites.append(invite)
        return type("Message", (), {"content": self.reponse})()


class ModeleInterdit:
    """Échoue si on l'appelle : sert à prouver qu'on n'interroge pas le modèle pour rien."""

    def invoke(self, invite: str) -> Any:
        raise AssertionError("le modèle ne doit pas être appelé ici")


def brancher(monkeypatch: pytest.MonkeyPatch, modele: Any) -> None:
    monkeypatch.setattr("jurismind.agents.dossier.modele_chat", lambda *a, **k: modele)
    monkeypatch.setattr(
        "jurismind.retrieval.recherche.modele_embeddings",
        lambda: type("E", (), {"embed_query": staticmethod(lambda _: [1.0] + [0.0] * (DIMENSION - 1))})(),
    )


@pytest.fixture
def dossier_garni(cabinet: Cabinet) -> int:
    """Le dossier de Me Dieng, avec deux pièces datées, un échange et un extrait indexé."""
    with Session(get_engine()) as session, session.begin():
        dossier = session.scalars(select(Dossier).where(Dossier.reference == "D2026-0024")).one()
        mise_en_demeure = Document(
            dossier_id=dossier.id,
            titre="Mise en demeure",
            sens=SensEchange.SORTANT,
            chemin_fichier="D2026-0024/mise-en-demeure.pdf",
            format="pdf",
            date_document=date(2026, 8, 13),
        )
        facture = Document(
            dossier_id=dossier.id,
            titre="Facture FA-2026-988",
            sens=SensEchange.ENTRANT,
            chemin_fichier="D2026-0024/facture.pdf",
            format="pdf",
            date_document=date(2026, 8, 9),
        )
        echange = Communication(
            dossier_id=dossier.id,
            canal=Canal.EMAIL,
            sens=SensEchange.ENTRANT,
            date_echange=datetime(2026, 8, 10, 9, tzinfo=UTC),
            expediteur="ndeye.diallo@sine.example",
            objet="Impayés Cap-Vert",
            corps="Le client ne règle pas.",
        )
        session.add_all([mise_en_demeure, facture, echange])
        session.flush()
        session.add(
            Extrait(
                document_id=mise_en_demeure.id,
                dossier_id=dossier.id,
                position=0,
                page=1,
                contenu="Vous êtes mis en demeure de régler la somme de 13 750 000 FCFA sous huit jours.",
                embedding=[1.0] + [0.0] * (DIMENSION - 1),
            )
        )
        return int(dossier.id)


# ------------------------------------------------------------------ aiguillage


def test_les_demandes_explicites_ne_derangent_pas_le_modele() -> None:
    assert deviner_intention("résume-moi ce dossier") is Intention.RESUME
    assert deviner_intention("donne-moi la chronologie") is Intention.CHRONOLOGIE
    assert deviner_intention("où en est la procédure ?") is Intention.RESUME
    assert deviner_intention("") is Intention.RESUME  # pas de demande : on synthétise


def test_une_question_precise_est_soumise_au_modele() -> None:
    assert deviner_intention("Le débiteur a-t-il formé opposition ?") is None


def test_un_aiguillage_illisible_retombe_sur_la_question(
    monkeypatch: pytest.MonkeyPatch, cabinet: Cabinet, dossier_garni: int
) -> None:
    """Si le modèle répond n'importe quoi, on traite la demande comme une question."""
    brancher(monkeypatch, ModeleSimule({"intention": "téléporter le dossier"}))
    monkeypatch.setattr(
        "jurismind.agents.dossier.repondre",
        lambda *a, **k: Reponse(texte="Oui.", citations=[], abstention=False),
    )
    with session_utilisateur(cabinet.dieng) as session:
        reponse = assister(session, cabinet.dieng, dossier_garni, "Et l'opposition ?")
    assert reponse.intention == "question"


# ------------------------------------------------------------------ chronologie


def test_la_chronologie_est_construite_par_le_code(
    monkeypatch: pytest.MonkeyPatch, cabinet: Cabinet, dossier_garni: int
) -> None:
    """Dates et libellés viennent de la base : le modèle n'est jamais appelé."""
    brancher(monkeypatch, ModeleInterdit())
    with session_utilisateur(cabinet.dieng) as session:
        reponse = assister(session, cabinet.dieng, dossier_garni, "chronologie du dossier")

    assert reponse.intention == "chronologie"
    assert not reponse.abstention
    lignes = reponse.texte.splitlines()
    assert lignes[0].startswith("09/08/2026")  # la facture, pièce la plus ancienne
    assert lignes[-1].startswith("13/08/2026")  # la mise en demeure, la plus récente
    assert "Impayés Cap-Vert — reçu de ndeye.diallo@sine.example" in reponse.texte
    assert len(reponse.donnees["evenements"]) == 3


def test_un_document_sans_date_nentre_pas_dans_la_chronologie(cabinet: Cabinet) -> None:
    """Le jugement du dossier de Me Fall n'a pas de date : il ne peut pas être situé."""
    with session_utilisateur(cabinet.fall) as session:
        dossier = session.scalars(select(Dossier).where(Dossier.reference == "D2026-0027")).one()
        assert evenements_du_dossier(session, dossier.id) == []


# ------------------------------------------------------------------ résumé


def test_un_resume_cite_ses_pieces(
    monkeypatch: pytest.MonkeyPatch, cabinet: Cabinet, dossier_garni: int
) -> None:
    modele = ModeleSimule({"resume": "Le débiteur doit 13 750 000 FCFA, mis en demeure le 13/08/2026."})
    brancher(monkeypatch, modele)
    with session_utilisateur(cabinet.dieng) as session:
        reponse = assister(session, cabinet.dieng, dossier_garni, "résume")

    assert reponse.intention == "resume"
    assert not reponse.abstention
    assert reponse.citations
    # La fiche et les événements sont fournis au modèle : il n'a pas à les deviner.
    assert "Mise en demeure" in modele.invites[0]
    assert "D2026-0024" in modele.invites[0]


def test_un_montant_absent_des_pieces_fait_abandonner_le_resume(
    monkeypatch: pytest.MonkeyPatch, cabinet: Cabinet, dossier_garni: int
) -> None:
    """Le chiffre inventé est le danger principal d'une synthèse : on préfère ne rien dire."""
    brancher(monkeypatch, ModeleSimule({"resume": "Le débiteur doit 42 000 000 FCFA."}))
    with session_utilisateur(cabinet.dieng) as session:
        reponse = assister(session, cabinet.dieng, dossier_garni, "résume")

    assert reponse.abstention
    assert "42 000 000" not in reponse.texte


def test_un_resume_vide_vaut_abstention(
    monkeypatch: pytest.MonkeyPatch, cabinet: Cabinet, dossier_garni: int
) -> None:
    brancher(monkeypatch, ModeleSimule("le modèle a répondu n'importe quoi"))
    with session_utilisateur(cabinet.dieng) as session:
        reponse = assister(session, cabinet.dieng, dossier_garni, "résume")
    assert reponse.abstention


# ------------------------------------------------------------------ question


def test_la_question_reutilise_la_reponse_citee(
    monkeypatch: pytest.MonkeyPatch, cabinet: Cabinet, dossier_garni: int
) -> None:
    """L'agent ne refait pas son propre RAG : il appelle celui qu'on a déjà vérifié."""
    brancher(monkeypatch, ModeleInterdit())  # l'aiguillage est décidé par mot-clé en amont
    appels: list[Any] = []
    etat_dossier = dossier_garni

    def repondre_simule(session: Any, question: str, filtres: Any = None, **_: Any) -> Reponse:
        appels.append(filtres)
        return Reponse(
            texte="Huit jours.",
            citations=[
                Citation(
                    numero=1,
                    reference="Mise en demeure, page 1",
                    extrait_id=1,
                    dossier_id=etat_dossier,
                )
            ],
            abstention=False,
        )

    monkeypatch.setattr("jurismind.agents.dossier.repondre", repondre_simule)
    monkeypatch.setattr("jurismind.agents.dossier.deviner_intention", lambda _: Intention.QUESTION)
    with session_utilisateur(cabinet.dieng) as session:
        reponse = assister(session, cabinet.dieng, dossier_garni, "Quel délai ?")

    assert reponse.texte == "Huit jours."
    assert reponse.citations[0]["reference"] == "Mise en demeure, page 1"
    # La recherche est bornée au dossier demandé, jamais à tout le cabinet.
    assert appels[0].dossier_id == dossier_garni


# ------------------------------------------------------------------ droits et traçabilité


def test_un_dossier_dautrui_ne_laisse_rien_filtrer(
    monkeypatch: pytest.MonkeyPatch, cabinet: Cabinet, dossier_garni: int
) -> None:
    """Me Fall interroge le dossier de Me Dieng : l'agent s'arrête avant toute recherche."""
    brancher(monkeypatch, ModeleInterdit())
    with session_utilisateur(cabinet.fall) as session:
        reponse = assister(session, cabinet.fall, dossier_garni, "résume")

    assert reponse.abstention
    assert reponse.texte == "Dossier introuvable."
    assert reponse.citations == []
    assert reponse.donnees["evenements"] == []


def test_lassistante_accede_au_dossier_quon_lui_a_confie(
    monkeypatch: pytest.MonkeyPatch, cabinet: Cabinet, dossier_garni: int
) -> None:
    brancher(monkeypatch, ModeleInterdit())
    with session_utilisateur(cabinet.sy) as session:
        reponse = assister(session, cabinet.sy, dossier_garni, "chronologie")
    assert not reponse.abstention
    assert len(reponse.donnees["evenements"]) == 3


def test_la_fiche_est_invisible_sans_acces(cabinet: Cabinet, dossier_garni: int) -> None:
    with session_utilisateur(cabinet.dieng) as session:
        assert fiche_dossier(session, dossier_garni) is not None
    with session_utilisateur(cabinet.fall) as session:
        assert fiche_dossier(session, dossier_garni) is None


def test_chaque_passage_de_lagent_est_journalise(
    monkeypatch: pytest.MonkeyPatch, cabinet: Cabinet, dossier_garni: int
) -> None:
    """Le cabinet doit pouvoir dire qui a demandé quoi, et si l'agent s'est abstenu."""
    brancher(monkeypatch, ModeleInterdit())
    with session_utilisateur(cabinet.dieng) as session:
        assister(session, cabinet.dieng, dossier_garni, "chronologie")
    with session_utilisateur(cabinet.fall) as session:
        assister(session, cabinet.fall, dossier_garni, "chronologie")

    with Session(get_engine()) as session:
        entrees = session.scalars(select(EntreeAudit).order_by(EntreeAudit.id)).all()
    actions = [(entree.utilisateur_id, entree.action, entree.details["abstention"]) for entree in entrees]
    assert (cabinet.dieng, "agent_dossier_chronologie", False) in actions
    assert (cabinet.fall, "agent_dossier_chronologie", True) in actions
