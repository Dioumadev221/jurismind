"""Le jeu d'évaluation et ses mesures : ce sont eux qui rendent la fiabilité vérifiable."""

from pathlib import Path

import pytest

from jurismind.evaluation.jeu import construire
from jurismind.evaluation.mesures import Bilan, Resultat, normaliser_valeur, valeur_presente

CORRIGE = Path("data/simulation/verite.json")


def sauter_sans_corrige() -> None:
    if not CORRIGE.exists():
        pytest.skip("corrigé absent : lancer `python -m simulation`")


# --------------------------------------------------------------------- comparaison des valeurs


@pytest.mark.parametrize(
    ("attendu", "reponse"),
    [
        ("2 000 000", "Le montant total est de 2 000 000 FCFA."),
        ("2 000 000", "Le montant est de 2000000 francs CFA."),
        ("8", "Un délai de huit jours, soit 8 jours ouvrés."),
        ("16/05/2024", "Signifiée le 16/05/2024 par huissier."),
    ],
)
def test_une_valeur_est_reconnue_malgre_la_mise_en_forme(attendu: str, reponse: str) -> None:
    assert valeur_presente(attendu, reponse)


def test_une_valeur_absente_nest_pas_reconnue() -> None:
    assert not valeur_presente("2 000 000", "Le montant est de 3 000 000 FCFA.")
    assert not valeur_presente("2 000 000", "Je ne trouve pas cette information.")


def test_les_espaces_et_le_texte_sont_ignores() -> None:
    assert normaliser_valeur("13 750 000 FCFA") == "13750000"


# --------------------------------------------------------------------- construction du jeu


def test_le_jeu_est_reproductible() -> None:
    sauter_sans_corrige()
    premier = construire(nombre=10, graine=3)
    second = construire(nombre=10, graine=3)
    assert [q.question for q in premier] == [q.question for q in second]


def test_le_jeu_melange_questions_avec_et_sans_reponse() -> None:
    sauter_sans_corrige()
    jeu = construire(nombre=20, graine=7)

    sans_reponse = [q for q in jeu if q.sans_reponse]
    avec_reponse = [q for q in jeu if not q.sans_reponse]
    assert len(jeu) == 20
    assert 2 <= len(sans_reponse) <= 6, "il faut des questions sans réponse pour mesurer l'abstention"
    assert all(q.attendu and q.document_attendu for q in avec_reponse)
    assert all(q.avocat_attendu for q in jeu), "chaque question est posée par un avocat du dossier"


def test_le_jeu_contient_des_questions_sur_des_scans() -> None:
    """Sans ces questions, l'OCR ne serait jamais évalué."""
    sauter_sans_corrige()
    jeu = construire(nombre=60, graine=1)
    assert any(q.categorie == "date_ocr" for q in jeu)


def test_un_corrige_manquant_est_signale_clairement(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match="python -m simulation"):
        construire(corrige=tmp_path / "absent.json")


# --------------------------------------------------------------------- calcul des indicateurs


def resultat(**champs: object) -> Resultat:
    valeurs: dict[str, object] = {
        "question": "Quel montant ?",
        "categorie": "montant",
        "attendu": ["2 000 000"],
        "reponse": "2 000 000 FCFA",
        "abstention": False,
        "juste": True,
        "source_trouvee": True,
        "source_citee": True,
        "citations": 1,
        "secondes": 5.0,
    }
    return Resultat(**{**valeurs, **champs})  # type: ignore[arg-type]


def test_les_indicateurs_separent_les_questions_avec_et_sans_reponse() -> None:
    bilan = Bilan(
        resultats=[
            resultat(),
            resultat(juste=False, reponse="3 000 000 FCFA"),
            resultat(
                attendu=[],
                reponse="Je ne trouve pas…",
                abstention=True,
                juste=False,
                source_trouvee=None,
                source_citee=None,
                citations=0,
            ),
        ]
    )
    resume = bilan.resume()

    assert resume["justesse"] == 50.0  # une bonne réponse sur deux questions répondables
    assert resume["abstention_correcte"] == 100.0
    assert resume["inventions"] == 1  # la réponse fausse et affirmative
    assert resume["rappel_recherche"] == 100.0


def test_un_silence_alors_que_la_source_etait_la_est_compte() -> None:
    bilan = Bilan(resultats=[resultat(abstention=True, juste=False, source_trouvee=True, citations=0)])
    assert bilan.resume()["silences_coupables"] == 1
    assert bilan.resume()["inventions"] == 0, "se taire n'est pas inventer"


def test_une_abstention_manquee_compte_comme_telle() -> None:
    """Question sans réponse à laquelle le système a quand même répondu."""
    bilan = Bilan(
        resultats=[
            resultat(
                attendu=[],
                reponse="La capitale est Dakar.",
                abstention=False,
                juste=False,
                source_trouvee=None,
                source_citee=None,
            )
        ]
    )
    assert bilan.resume()["abstention_correcte"] == 0.0


def test_le_bilan_est_exportable_en_json() -> None:
    bilan = Bilan(resultats=[resultat()])
    donnees = bilan.en_json()
    assert set(donnees) == {"resume", "detail"}
    assert donnees["detail"][0]["question"] == "Quel montant ?"
