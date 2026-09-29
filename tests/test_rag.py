"""La génération de réponses : citations vérifiées, abstention, rien d'inventé.

Le modèle est simulé : on teste nos garde-fous, pas la qualité d'Ollama (mesurée
séparément par le jeu d'évaluation).
"""

import json
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from jurismind.db.models import Dossier, Extrait
from jurismind.db.session import get_engine, session_utilisateur
from jurismind.rag import repondre
from jurismind.rag.reponse import PHRASE_ABSTENTION, _citations_valides, _lire_json
from jurismind.retrieval.recherche import Resultat
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
        raise AssertionError("le modèle ne doit pas être appelé sans source")


@pytest.fixture
def extrait_dieng(cabinet: Cabinet) -> int:
    with Session(get_engine()) as session, session.begin():
        dossier = session.scalars(select(Dossier).where(Dossier.reference == "D2026-0024")).one()
        extrait = Extrait(
            dossier_id=dossier.id,
            document_id=None,
            communication_id=None,
            position=0,
            contenu="Le débiteur dispose d'un délai de quinze jours pour former opposition.",
            embedding=[1.0] + [0.0] * (DIMENSION - 1),
        )
        # Un extrait doit venir d'un document ou d'un échange : on le rattache au jugement.
        from jurismind.db.models import Document

        document = session.scalars(select(Document)).first()
        assert document is not None
        extrait.document_id = document.id
        extrait.dossier_id = dossier.id
        session.add(extrait)
        session.flush()
        return extrait.id


def brancher(monkeypatch: pytest.MonkeyPatch, modele: Any) -> None:
    monkeypatch.setattr("jurismind.rag.reponse.modele_chat", lambda *a, **k: modele)
    monkeypatch.setattr(
        "jurismind.retrieval.recherche.modele_embeddings",
        lambda: type("E", (), {"embed_query": staticmethod(lambda _: [1.0] + [0.0] * (DIMENSION - 1))})(),
    )


# --------------------------------------------------------------------- lecture du JSON


def test_le_json_est_lu_meme_entoure_de_texte() -> None:
    assert _lire_json('Voici :\n{"reponse": "ok", "sources": [1]}\nvoilà') == {
        "reponse": "ok",
        "sources": [1],
    }
    assert _lire_json("pas de json du tout") is None


# --------------------------------------------------------------------- citations


def _resultats(nombre: int) -> list[Resultat]:
    class ExtraitFactice:
        def __init__(self, identifiant: int) -> None:
            self.id = identifiant
            self.dossier_id = 1
            self.page = 1
            self.document = None
            self.communication = None

    return [Resultat(extrait=ExtraitFactice(n), score=1.0) for n in range(1, nombre + 1)]  # type: ignore[arg-type]


def test_une_citation_inventee_est_ecartee() -> None:
    citations = _citations_valides([1, 9, "2", None], _resultats(3))
    assert [c.numero for c in citations] == [1, 2]


def test_une_citation_repetee_nest_comptee_quune_fois() -> None:
    assert [c.numero for c in _citations_valides([2, 2, 2], _resultats(3))] == [2]


# --------------------------------------------------------------------- réponses


def test_une_reponse_citee_est_acceptee(
    monkeypatch: pytest.MonkeyPatch, cabinet: Cabinet, extrait_dieng: int
) -> None:
    brancher(
        monkeypatch,
        ModeleSimule(
            {
                "reponse": "Quinze jours.",
                "sources": [1],
                "citation": "Le débiteur dispose d'un délai de quinze jours pour former opposition.",
            }
        ),
    )

    with session_utilisateur(cabinet.dieng) as session:
        reponse = repondre(session, "Quel délai pour former opposition ?")

    assert not reponse.abstention
    assert reponse.texte == "Quinze jours."
    assert reponse.citations and reponse.citations[0].numero == 1
    assert reponse.fiable


def test_une_reponse_sans_source_est_refusee(
    monkeypatch: pytest.MonkeyPatch, cabinet: Cabinet, extrait_dieng: int
) -> None:
    brancher(monkeypatch, ModeleSimule({"reponse": "Trente jours.", "sources": [], "citation": ""}))

    with session_utilisateur(cabinet.dieng) as session:
        reponse = repondre(session, "Quel délai ?")

    assert reponse.abstention
    assert reponse.texte == PHRASE_ABSTENTION
    assert reponse.citations == []


def test_une_source_inexistante_ne_valide_pas_la_reponse(
    monkeypatch: pytest.MonkeyPatch, cabinet: Cabinet, extrait_dieng: int
) -> None:
    brancher(monkeypatch, ModeleSimule({"reponse": "Trente jours.", "sources": [42], "citation": "x"}))

    with session_utilisateur(cabinet.dieng) as session:
        reponse = repondre(session, "Quel délai ?")

    assert reponse.abstention, "une citation inventée ne doit pas suffire à valider une réponse"


def test_un_aveu_dignorance_reste_une_abstention(
    monkeypatch: pytest.MonkeyPatch, cabinet: Cabinet, extrait_dieng: int
) -> None:
    # Cas observé avec un petit modèle : il dit ne pas savoir, mais cite quand même une source.
    brancher(
        monkeypatch,
        ModeleSimule(
            {
                "reponse": "Cette information ne figure pas dans les sources.",
                "sources": [1],
                "citation": "Le débiteur dispose d'un délai de quinze jours pour former opposition.",
            }
        ),
    )

    with session_utilisateur(cabinet.dieng) as session:
        reponse = repondre(session, "Quelle est la capitale de la France ?")

    assert reponse.abstention


def test_une_reponse_illisible_provoque_une_abstention(
    monkeypatch: pytest.MonkeyPatch, cabinet: Cabinet, extrait_dieng: int
) -> None:
    brancher(monkeypatch, ModeleSimule("le modèle a répondu n'importe quoi"))

    with session_utilisateur(cabinet.dieng) as session:
        reponse = repondre(session, "Quel délai ?")

    assert reponse.abstention


def test_sans_extrait_le_modele_nest_meme_pas_appele(
    monkeypatch: pytest.MonkeyPatch, cabinet: Cabinet
) -> None:
    brancher(monkeypatch, ModeleInterdit())

    # L'administrateur n'a accès à aucun dossier : la recherche ne renvoie rien.
    with session_utilisateur(cabinet.admin) as session:
        reponse = repondre(session, "Quel délai pour former opposition ?")

    assert reponse.abstention
    assert reponse.sources_examinees == 0


def test_les_sources_sont_numerotees_dans_linvite(
    monkeypatch: pytest.MonkeyPatch, cabinet: Cabinet, extrait_dieng: int
) -> None:
    modele = ModeleSimule(
        {
            "reponse": "Quinze jours.",
            "sources": [1],
            "citation": "Le débiteur dispose d'un délai de quinze jours pour former opposition.",
        }
    )
    brancher(monkeypatch, modele)

    with session_utilisateur(cabinet.dieng) as session:
        repondre(session, "Quel délai ?")

    invite = modele.invites[0]
    assert "[1]" in invite
    assert "quinze jours" in invite.lower(), "l'extrait retrouvé doit être fourni au modèle"


def test_un_avocat_ne_recoit_jamais_les_sources_dun_autre(
    monkeypatch: pytest.MonkeyPatch, cabinet: Cabinet, extrait_dieng: int
) -> None:
    modele = ModeleSimule(
        {
            "reponse": "Quinze jours.",
            "sources": [1],
            "citation": "Le débiteur dispose d'un délai de quinze jours pour former opposition.",
        }
    )
    brancher(monkeypatch, modele)

    with session_utilisateur(cabinet.fall) as session:
        repondre(session, "Quel délai pour former opposition ?")

    if modele.invites:
        assert "quinze jours" not in modele.invites[0].lower()


# --------------------------------------------------------------------- vérifications renforcées


def test_une_citation_inventee_fait_echouer_la_reponse(
    monkeypatch: pytest.MonkeyPatch, cabinet: Cabinet, extrait_dieng: int
) -> None:
    """Cas réel : le modèle répond « la capitale du Sénégal est Dakar » en citant une source."""
    brancher(
        monkeypatch,
        ModeleSimule(
            {
                "reponse": "La capitale du Sénégal est Dakar.",
                "sources": [1],
                "citation": "La capitale du Sénégal est Dakar, chef-lieu de la région.",
            }
        ),
    )

    with session_utilisateur(cabinet.dieng) as session:
        reponse = repondre(session, "Quelle est la capitale du Sénégal ?")

    assert reponse.abstention, "la citation ne figure dans aucune source : la réponse est écartée"


def test_une_reference_absente_de_la_source_fait_echouer_la_reponse(
    monkeypatch: pytest.MonkeyPatch, cabinet: Cabinet, extrait_dieng: int
) -> None:
    """Cas réel : le montant donné venait d'une autre facture que celle demandée."""
    brancher(
        monkeypatch,
        ModeleSimule(
            {
                "reponse": "Le montant de la facture FA-2023-702 est de 6 150 000 FCFA.",
                "sources": [1],
                "citation": "Le débiteur dispose d'un délai de quinze jours pour former opposition.",
            }
        ),
    )

    with session_utilisateur(cabinet.dieng) as session:
        reponse = repondre(session, "Quel est le montant de la facture FA-2023-702 ?")

    assert reponse.abstention


def test_une_citation_legerement_reformulee_reste_acceptee(
    monkeypatch: pytest.MonkeyPatch, cabinet: Cabinet, extrait_dieng: int
) -> None:
    """On ne veut pas refuser une bonne réponse pour un mot de liaison en trop."""
    brancher(
        monkeypatch,
        ModeleSimule(
            {
                "reponse": "Quinze jours.",
                "sources": [1],
                "citation": "le débiteur dispose d un délai de quinze jours pour former opposition",
            }
        ),
    )

    with session_utilisateur(cabinet.dieng) as session:
        reponse = repondre(session, "Quel délai ?")

    assert not reponse.abstention
