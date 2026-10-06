"""L'agent d'analyse de documents : un type connu, des citations réelles, des droits tenus.

Le modèle est simulé. On vérifie les trois garanties de l'agent : le type retenu appartient
à la liste du cabinet, un point clé n'est affiché que si sa phrase est dans le document, et
une pièce d'un dossier qu'on ne voit pas ne laisse rien filtrer.
"""

import json
from datetime import date
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from jurismind.agents.analyse import (
    CARACTERES_MAX,
    POINTS_MAX,
    assister,
    categorie_valide,
    citations_affirmees,
    points_verifies,
    texte_utile,
)
from jurismind.agents.outils import documents_du_dossier, extraction_du_document, fiche_document
from jurismind.db.models import (
    Document,
    Dossier,
    EntreeAudit,
    Extraction,
    SensEchange,
    StatutExtraction,
    StatutTraitement,
)
from jurismind.db.session import get_engine, session_utilisateur
from jurismind.rag.reponse import Citation, Reponse
from tests.conftest import Cabinet

TEXTE = (
    "CABINET TÉRANGA AVOCATS\n"
    "MISE EN DEMEURE\n"
    "Nous vous mettons en demeure de régler la somme de 13 750 000 FCFA "
    "dans un délai de huit jours à compter de la réception de la présente.\n"
    "À défaut, une procédure d'injonction de payer sera engagée devant le "
    "Tribunal de commerce de Dakar."
)


class ModeleScenario:
    """Répond une chose différente à chaque appel : classement, résumé, puis points."""

    def __init__(self, *reponses: Any) -> None:
        self.reponses = [r if isinstance(r, str) else json.dumps(r) for r in reponses]
        self.invites: list[str] = []

    def invoke(self, invite: str) -> Any:
        self.invites.append(invite)
        brut = self.reponses[min(len(self.invites) - 1, len(self.reponses) - 1)]
        return type("Message", (), {"content": brut})()


class ModeleInterdit:
    def invoke(self, invite: str) -> Any:
        raise AssertionError("le modèle ne doit pas être appelé ici")


def brancher(monkeypatch: pytest.MonkeyPatch, modele: Any) -> None:
    monkeypatch.setattr("jurismind.agents.analyse.modele_chat", lambda *a, **k: modele)


def scenario_complet(points: list[dict[str, Any]] | None = None) -> ModeleScenario:
    return ModeleScenario(
        {"type": "MISE_EN_DEMEURE"},
        {"resume": "Le cabinet met en demeure le débiteur de régler 13 750 000 FCFA."},
        {
            "points": points
            if points is not None
            else [
                {"titre": "délai", "citation": "dans un délai de huit jours"},
                {"titre": "montant", "citation": "la somme de 13 750 000 FCFA"},
            ]
        },
    )


@pytest.fixture
def piece(cabinet: Cabinet) -> int:
    """Une mise en demeure du dossier de Me Dieng, saisie « DIVERS » par le cabinet."""
    with Session(get_engine()) as session, session.begin():
        dossier = session.scalars(select(Dossier).where(Dossier.reference == "D2026-0024")).one()
        document = Document(
            dossier_id=dossier.id,
            titre="Courrier du 13/08/2026",
            categorie_source="DIVERS",
            sens=SensEchange.SORTANT,
            chemin_fichier="D2026-0024/courrier.pdf",
            format="pdf",
            date_document=date(2026, 8, 13),
            statut_traitement=StatutTraitement.TRAITE,
            texte=TEXTE,
        )
        session.add(document)
        session.flush()
        return int(document.id)


# ------------------------------------------------------------------ garde-fous unitaires


def test_un_type_hors_liste_est_ecarte() -> None:
    """Le modèle ne crée pas de vocabulaire : hors de la liste du cabinet, rien n'est retenu."""
    assert categorie_valide("mise_en_demeure") == "MISE_EN_DEMEURE"
    assert categorie_valide("  bail-commercial ") is None
    assert categorie_valide("LETTRE_DE_RELANCE") is None
    assert categorie_valide("") is None


def test_un_type_ecrit_autrement_est_rattrape() -> None:
    assert categorie_valide("Ordonnance IP") == "ORDONNANCE_IP"
    assert categorie_valide("pv-signification") == "PV_SIGNIFICATION"


def test_un_point_dont_la_phrase_est_absente_est_ecarte() -> None:
    proposes = [
        {"titre": "délai", "citation": "dans un délai de huit jours"},
        {"titre": "pénalité", "citation": "une pénalité de 10 % par mois de retard"},
    ]
    retenus = points_verifies(proposes, TEXTE)
    assert [point.titre for point in retenus] == ["délai"]


def test_une_citation_vide_nest_pas_un_rejet() -> None:
    """Le modèle énumère les natures de points et met null sur celles qu'il ne trouve pas."""
    proposes = [
        {"titre": "délai", "citation": "dans un délai de huit jours"},
        {"titre": "pénalité", "citation": None},
        {"titre": "garantie", "citation": ""},
    ]
    assert len(points_verifies(proposes, TEXTE)) == 1
    assert citations_affirmees(proposes) == 1  # une seule citation réellement avancée


def test_une_citation_repetee_nest_gardee_quune_fois() -> None:
    propose = {"titre": "délai", "citation": "dans un délai de huit jours"}
    assert len(points_verifies([propose, dict(propose)], TEXTE)) == 1


def test_le_nombre_de_points_est_borne() -> None:
    proposes = [{"titre": f"p{n}", "citation": f"la somme de 13 750 000 FCFA {n}"} for n in range(12)]
    assert len(points_verifies(proposes, TEXTE)) <= POINTS_MAX


def test_une_entree_mal_formee_ne_casse_rien() -> None:
    assert points_verifies(["du texte", None, 42, {}], TEXTE) == []


def test_un_acte_trop_long_est_rogne_au_milieu() -> None:
    """On garde l'en-tête et le dispositif : c'est là que sont les parties et les montants."""
    long = "DEBUT" + "x" * (3 * CARACTERES_MAX) + "FIN"
    rogne = texte_utile(long)
    assert len(rogne) < len(long)
    assert rogne.startswith("DEBUT")
    assert rogne.endswith("FIN")
    assert texte_utile(TEXTE) == TEXTE


# ------------------------------------------------------------------ outils de lecture


def test_la_fiche_du_document_porte_son_texte_et_son_dossier(cabinet: Cabinet, piece: int) -> None:
    with session_utilisateur(cabinet.dieng) as session:
        fiche = fiche_document(session, piece)
    assert fiche is not None
    assert fiche["dossier"] == "D2026-0024"
    assert fiche["categorie_source"] == "DIVERS"
    assert fiche["caracteres"] == len(TEXTE)


def test_une_piece_dun_dossier_dautrui_est_invisible(cabinet: Cabinet, piece: int) -> None:
    with session_utilisateur(cabinet.fall) as session:
        assert fiche_document(session, piece) is None
        assert extraction_du_document(session, piece) is None


def test_les_pieces_dun_dossier_se_listent(cabinet: Cabinet, piece: int) -> None:
    with session_utilisateur(cabinet.dieng) as session:
        dossier = session.scalars(select(Dossier).where(Dossier.reference == "D2026-0024")).one()
        pieces = documents_du_dossier(session, dossier.id)
    assert [document["id"] for document in pieces] == [piece]


# ------------------------------------------------------------------ l'agent


def test_lanalyse_reconnait_le_type_et_signale_le_desaccord(
    monkeypatch: pytest.MonkeyPatch, cabinet: Cabinet, piece: int
) -> None:
    brancher(monkeypatch, scenario_complet())
    with session_utilisateur(cabinet.dieng) as session:
        reponse = assister(session, cabinet.dieng, piece)

    assert reponse.intention == "analyse"
    assert not reponse.abstention
    assert reponse.donnees["categorie_detectee"] == "MISE_EN_DEMEURE"
    assert reponse.donnees["desaccord_categorie"] is True
    assert "Le cabinet avait saisi : DIVERS" in reponse.texte
    assert [point["titre"] for point in reponse.donnees["points_cles"]] == ["délai", "montant"]


def test_le_type_reconnu_est_inscrit_en_base(
    monkeypatch: pytest.MonkeyPatch, cabinet: Cabinet, piece: int
) -> None:
    """C'est ce qui permet à l'extraction de choisir le bon schéma (ADR 0004)."""
    brancher(monkeypatch, scenario_complet())
    with session_utilisateur(cabinet.dieng) as session:
        assister(session, cabinet.dieng, piece)

    with Session(get_engine()) as session:
        document = session.get(Document, piece)
        assert document is not None
        assert document.categorie_detectee == "MISE_EN_DEMEURE"
        assert document.categorie_source == "DIVERS"  # la saisie du cabinet n'est pas écrasée


def test_un_type_hors_liste_laisse_la_base_intacte(
    monkeypatch: pytest.MonkeyPatch, cabinet: Cabinet, piece: int
) -> None:
    brancher(
        monkeypatch,
        ModeleScenario(
            {"type": "LETTRE_DE_RELANCE"},
            {"resume": "Un courrier réclamant 13 750 000 FCFA."},
            {"points": []},
        ),
    )
    with session_utilisateur(cabinet.dieng) as session:
        reponse = assister(session, cabinet.dieng, piece)

    assert reponse.donnees["categorie_detectee"] == ""
    assert "Type reconnu : non déterminé" in reponse.texte
    with Session(get_engine()) as session:
        document = session.get(Document, piece)
        assert document is not None
        assert document.categorie_detectee is None


def test_un_resume_avec_un_montant_absent_du_document_est_ecarte(
    monkeypatch: pytest.MonkeyPatch, cabinet: Cabinet, piece: int
) -> None:
    """Le reste de l'analyse subsiste : seule la phrase non vérifiable disparaît."""
    brancher(
        monkeypatch,
        ModeleScenario(
            {"type": "MISE_EN_DEMEURE"},
            {"resume": "Le cabinet réclame 42 000 000 FCFA."},
            {"points": [{"titre": "délai", "citation": "dans un délai de huit jours"}]},
        ),
    )
    with session_utilisateur(cabinet.dieng) as session:
        reponse = assister(session, cabinet.dieng, piece)

    assert reponse.donnees["resume"] == ""
    assert "42 000 000" not in reponse.texte
    assert reponse.donnees["points_cles"]  # le relevé, lui, est vérifié et conservé


def test_les_valeurs_deja_extraites_sont_rappelees(
    monkeypatch: pytest.MonkeyPatch, cabinet: Cabinet, piece: int
) -> None:
    with Session(get_engine()) as session, session.begin():
        session.add(
            Extraction(
                document_id=piece,
                schema="MiseEnDemeure",
                donnees={"montant_reclame_fcfa": 13_750_000, "delai_jours": 8, "vide": None},
                champs_douteux=["delai_jours"],
                statut=StatutExtraction.PROPOSEE,
            )
        )
    brancher(monkeypatch, scenario_complet())
    with session_utilisateur(cabinet.dieng) as session:
        reponse = assister(session, cabinet.dieng, piece)

    extraction = reponse.donnees["extraction"]
    assert extraction is not None
    assert "vide" not in extraction["donnees"]  # les champs vides ne remontent pas
    assert "À relire : delai_jours" in reponse.texte


def test_une_question_sur_la_piece_est_bornee_a_son_dossier(
    monkeypatch: pytest.MonkeyPatch, cabinet: Cabinet, piece: int
) -> None:
    brancher(monkeypatch, ModeleInterdit())  # une question ne passe pas par le classement
    filtres_recus: list[Any] = []

    def repondre_simule(session: Any, question: str, filtres: Any = None, **_: Any) -> Reponse:
        filtres_recus.append(filtres)
        return Reponse(
            texte="Huit jours.",
            citations=[Citation(numero=1, reference="Courrier, page 1", extrait_id=1, dossier_id=None)],
            abstention=False,
        )

    monkeypatch.setattr("jurismind.agents.analyse.repondre", repondre_simule)
    with session_utilisateur(cabinet.dieng) as session:
        reponse = assister(session, cabinet.dieng, piece, "Quel délai est accordé ?")

    assert reponse.intention == "question"
    assert reponse.texte == "Huit jours."
    assert filtres_recus[0].dossier_id is not None


def test_une_piece_dautrui_ne_laisse_rien_filtrer(
    monkeypatch: pytest.MonkeyPatch, cabinet: Cabinet, piece: int
) -> None:
    brancher(monkeypatch, ModeleInterdit())
    with session_utilisateur(cabinet.fall) as session:
        reponse = assister(session, cabinet.fall, piece)

    assert reponse.abstention
    assert reponse.texte == "Document introuvable."
    assert reponse.donnees["points_cles"] == []


def test_un_document_pas_encore_lu_ne_fait_pas_appel_au_modele(
    monkeypatch: pytest.MonkeyPatch, cabinet: Cabinet
) -> None:
    """Sans texte, il n'y a rien à analyser : on le dit, on ne devine pas."""
    with Session(get_engine()) as session, session.begin():
        dossier = session.scalars(select(Dossier).where(Dossier.reference == "D2026-0024")).one()
        document = Document(
            dossier_id=dossier.id,
            titre="Scan à traiter",
            sens=SensEchange.ENTRANT,
            chemin_fichier="D2026-0024/scan.pdf",
            format="pdf",
        )
        session.add(document)
        session.flush()
        identifiant = int(document.id)

    brancher(monkeypatch, ModeleInterdit())
    with session_utilisateur(cabinet.dieng) as session:
        reponse = assister(session, cabinet.dieng, identifiant, "")
    assert reponse.abstention
    assert "ingestion" in reponse.texte


def test_chaque_analyse_est_journalisee(
    monkeypatch: pytest.MonkeyPatch, cabinet: Cabinet, piece: int
) -> None:
    brancher(monkeypatch, scenario_complet())
    with session_utilisateur(cabinet.dieng) as session:
        assister(session, cabinet.dieng, piece)

    with Session(get_engine()) as session:
        entree = session.scalars(select(EntreeAudit).order_by(EntreeAudit.id.desc())).first()
    assert entree is not None
    assert entree.action == "agent_document_analyse"
    assert entree.details["categorie_detectee"] == "MISE_EN_DEMEURE"
    assert entree.details["desaccord_categorie"] is True
    assert entree.details["points_retenus"] == 2
    assert entree.dossier_id is not None
