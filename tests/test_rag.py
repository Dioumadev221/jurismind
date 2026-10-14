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
    """Coupe le test de **tous** les services de modèle, rédaction et contrôle compris.

    Le juge d'implication est un second service : le laisser branché ferait appeler Ollama
    par des tests qui ne parlent pas de lui, ce qui les rend lents et non reproductibles —
    et c'est précisément la faute qui avait déjà rendu l'intégration continue rouge. Il
    confirme par défaut ; les tests qui s'intéressent à lui le rebranchent avec
    `brancher_juge`.
    """
    monkeypatch.setattr("jurismind.rag.reponse.modele_chat", lambda *a, **k: modele)
    brancher_juge(monkeypatch, '{"soutenue": true}')
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


@pytest.fixture
def facture_scannee(cabinet: Cabinet) -> int:
    """Une facture dont l'OCR a abîmé l'en-tête : le numéro ne survit que dans le titre.

    Cas réel du corpus : « FACTURE N° FA-2025-994 » est ressorti du scan en « FACTURE N4 ».
    Le montant, lui, est intact. Un contrôle qui ne lirait que le corps conclurait que la
    pièce demandée n'est pas là, et ferait taire une réponse juste.
    """
    from jurismind.db.models import Document, SensEchange

    with Session(get_engine()) as session, session.begin():
        dossier = session.scalars(select(Dossier).where(Dossier.reference == "D2026-0024")).one()
        document = Document(
            dossier_id=dossier.id,
            titre="Facture FA-2025-994",
            sens=SensEchange.ENTRANT,
            chemin_fichier="D2026-0024/FA-2025-994.pdf",
            format="pdf",
            ocr_utilise=True,
        )
        session.add(document)
        session.flush()
        extrait = Extrait(
            dossier_id=dossier.id,
            document_id=document.id,
            position=0,
            contenu="FACTURE N4\nDate : 17/01/2025\nMontant total TTC : 5 100 000 FCFA",
            embedding=[1.0] + [0.0] * (DIMENSION - 1),
        )
        session.add(extrait)
        session.flush()
        return extrait.id


def test_un_numero_abime_par_locr_ne_fait_plus_taire_la_reponse(
    monkeypatch: pytest.MonkeyPatch, cabinet: Cabinet, facture_scannee: int
) -> None:
    """Le titre identifie la pièce aussi sûrement que son en-tête scanné."""
    brancher(
        monkeypatch,
        ModeleSimule(
            {
                "reponse": "La facture FA-2025-994 s'élève à 5 100 000 FCFA.",
                "sources": [1],
                "citation": "Montant total TTC : 5 100 000 FCFA",
            }
        ),
    )

    with session_utilisateur(cabinet.dieng) as session:
        reponse = repondre(session, "Quel est le montant de la facture FA-2025-994 ?")

    assert reponse.controles["references"] is True
    assert not reponse.abstention
    assert "5 100 000" in reponse.texte


def test_une_facture_voisine_fait_toujours_echouer_le_controle(
    monkeypatch: pytest.MonkeyPatch, cabinet: Cabinet, facture_scannee: int
) -> None:
    """Le garde-fou n'est pas desserré : le numéro demandé n'est ni dans le corps ni au titre."""
    brancher(
        monkeypatch,
        ModeleSimule(
            {
                "reponse": "La facture FA-2025-111 s'élève à 5 100 000 FCFA.",
                "sources": [1],
                "citation": "Montant total TTC : 5 100 000 FCFA",
            }
        ),
    )

    with session_utilisateur(cabinet.dieng) as session:
        reponse = repondre(session, "Quel est le montant de la facture FA-2025-111 ?")

    assert reponse.controles["references"] is False
    assert reponse.abstention


# ------------------------------------------------- déclenchement du contrôle d'implication


def brancher_juge(monkeypatch: pytest.MonkeyPatch, verdict: str) -> list[str]:
    """Remplace le juge d'implication et renvoie la liste de ses invites."""
    invites: list[str] = []

    class Juge:
        def invoke(self, invite: str) -> Any:
            invites.append(invite)
            return type("Message", (), {"content": verdict})()

    monkeypatch.setattr("jurismind.rag.implication.modele_chat", lambda *a, **k: Juge())
    return invites


def test_une_reponse_dont_les_chiffres_sont_ancres_ne_derange_pas_le_juge(
    monkeypatch: pytest.MonkeyPatch, cabinet: Cabinet, facture_scannee: int
) -> None:
    """Montants, délais, dates : l'essentiel du trafic reste à un seul appel au modèle.

    Le juge est branché pour **refuser**. S'il était consulté, la réponse serait écartée ;
    elle passe, donc il ne l'a pas été.
    """
    brancher(
        monkeypatch,
        ModeleSimule(
            {
                # Sans répéter le numéro de la pièce : l'OCR l'a abîmé dans le corps, donc
                # ses chiffres n'y figurent pas et la réponse cesserait d'être ancrée.
                "reponse": "Le montant total s'élève à 5 100 000 FCFA.",
                "sources": [1],
                "citation": "Montant total TTC : 5 100 000 FCFA",
            }
        ),
    )
    invites = brancher_juge(monkeypatch, '{"soutenue": false}')

    with session_utilisateur(cabinet.dieng) as session:
        reponse = repondre(session, "Quel est le montant de la facture FA-2025-994 ?")

    assert invites == [], "les chiffres concordaient : le juge n'avait rien à trancher"
    assert "implication" not in reponse.controles
    assert not reponse.abstention


def test_une_reponse_sans_chiffre_ancre_est_soumise_au_juge(
    monkeypatch: pytest.MonkeyPatch, cabinet: Cabinet, extrait_dieng: int
) -> None:
    """Une phrase recopiée peut être authentique sans rien prouver : c'est le cas « Dakar »."""
    brancher(
        monkeypatch,
        ModeleSimule(
            {
                "reponse": "La capitale du Sénégal est Dakar.",
                "sources": [1],
                "citation": "Le débiteur dispose d'un délai de quinze jours pour former opposition.",
            }
        ),
    )
    invites = brancher_juge(monkeypatch, '{"soutenue": false}')

    with session_utilisateur(cabinet.dieng) as session:
        reponse = repondre(session, "Quelle est la capitale du Sénégal ?")

    assert len(invites) == 1, "aucun chiffre n'ancrait la réponse : le juge devait trancher"
    assert reponse.controles["implication"] is False
    assert reponse.abstention


def test_le_juge_peut_confirmer_une_reponse_sans_chiffre(
    monkeypatch: pytest.MonkeyPatch, cabinet: Cabinet, extrait_dieng: int
) -> None:
    """Le contrôle ne doit pas faire taire ce qui est réellement soutenu par la pièce."""
    brancher(
        monkeypatch,
        ModeleSimule(
            {
                "reponse": "Le débiteur peut former opposition.",
                "sources": [1],
                "citation": "Le débiteur dispose d'un délai de quinze jours pour former opposition.",
            }
        ),
    )
    brancher_juge(monkeypatch, '{"soutenue": true}')

    with session_utilisateur(cabinet.dieng) as session:
        reponse = repondre(session, "Le débiteur peut-il former opposition ?")

    assert reponse.controles["implication"] is True
    assert not reponse.abstention


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


# --------------------------------------------------------------------- détail des contrôles


def test_une_reponse_acceptee_a_ses_quatre_controles_au_vert(
    monkeypatch: pytest.MonkeyPatch, cabinet: Cabinet, extrait_dieng: int
) -> None:
    brancher(
        monkeypatch,
        ModeleSimule(
            {
                "reponse": "Quinze jours.",
                "sources": [1],
                "citation": "un délai de quinze jours pour former opposition",
            }
        ),
    )
    with session_utilisateur(cabinet.dieng) as session:
        reponse = repondre(session, "Quel délai pour former opposition ?")
    assert not reponse.abstention
    # « Quinze jours. » ne porte aucun chiffre : l'ancrage passe par la citation recopiée,
    # donc le cinquième contrôle s'exerce et figure dans le verdict.
    assert reponse.controles == {
        "sources": True,
        "ignorance": True,
        "references": True,
        "ancrage": True,
        "implication": True,
    }


def test_une_reponse_sans_citation_echoue_au_controle_des_sources(
    monkeypatch: pytest.MonkeyPatch, cabinet: Cabinet, extrait_dieng: int
) -> None:
    """L'interface doit pouvoir dire lequel des quatre contrôles a bloqué la réponse."""
    brancher(monkeypatch, ModeleSimule({"reponse": "Trente jours.", "sources": [], "citation": ""}))
    with session_utilisateur(cabinet.dieng) as session:
        reponse = repondre(session, "Quel délai ?")
    assert reponse.abstention
    assert reponse.controles["sources"] is False


def test_un_chiffre_invente_echoue_au_controle_dancrage(
    monkeypatch: pytest.MonkeyPatch, cabinet: Cabinet, extrait_dieng: int
) -> None:
    brancher(
        monkeypatch,
        ModeleSimule(
            {"reponse": "Trente jours.", "sources": [1], "citation": "une phrase inventée de toutes pièces"}
        ),
    )
    with session_utilisateur(cabinet.dieng) as session:
        reponse = repondre(session, "Quel délai ?")
    assert reponse.abstention
    assert reponse.controles["sources"] is True  # la source citée existe bien
    assert reponse.controles["ancrage"] is False  # mais rien n'y ancre « trente »


def test_sans_extrait_aucun_controle_ne_sexerce(monkeypatch: pytest.MonkeyPatch, cabinet: Cabinet) -> None:
    """Vide, et non « tout faux » : il n'y avait rien à vérifier."""
    brancher(monkeypatch, ModeleInterdit())
    with session_utilisateur(cabinet.dieng) as session:
        reponse = repondre(session, "Une question sans pièce")
    assert reponse.abstention
    assert reponse.controles == {}
