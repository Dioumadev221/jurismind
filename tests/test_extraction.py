"""L'extraction structurée : conversion des valeurs, contrôle, validation par un avocat."""

import json
from datetime import date
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from jurismind.db.models import Document, Extraction, SensEchange, StatutExtraction, StatutTraitement
from jurismind.db.session import get_engine, session_utilisateur
from jurismind.evaluation.extraction import valeurs_equivalentes
from jurismind.extraction.extracteur import (
    champs_attendus,
    champs_douteux,
    convertir,
    enregistrer,
    extraire,
    texte_utile,
    valider,
)
from jurismind.extraction.schemas import Facture, MiseEnDemeure, schema_pour
from tests.conftest import Cabinet

TEXTE_FACTURE = (
    "Sine Services SA\nRCCM : SN-THS-2007-B-97463\n"
    "FACTURE N° FA-2025-978\nDate : 09/08/2025\nDoit : Cap-Vert Immobilier SARL\n"
    "Montant total TTC : 2 000 000 FCFA\n"
    "Conditions de paiement : à 30 jours date de facture."
)


class ModeleSimule:
    """Renvoie le JSON choisi par le test, à la place d'Ollama."""

    def __init__(self, reponse: Any) -> None:
        self.reponse = reponse if isinstance(reponse, str) else json.dumps(reponse)
        self.invites: list[str] = []

    def invoke(self, invite: str) -> Any:
        self.invites.append(invite)
        return type("Message", (), {"content": self.reponse})()


@pytest.fixture
def document_facture(cabinet: Cabinet) -> int:
    with Session(get_engine()) as session, session.begin():
        document = session.scalars(select(Document)).first()
        assert document is not None
        document.categorie_source = "FACTURE"
        document.texte = TEXTE_FACTURE
        document.statut_traitement = StatutTraitement.TRAITE
        return document.id


# --------------------------------------------------------------------- schémas


def test_chaque_categorie_connue_a_son_schema() -> None:
    assert schema_pour("FACTURE") is Facture
    assert schema_pour("mise_en_demeure") is MiseEnDemeure
    assert schema_pour("DIVERS") is None  # catégorie fourre-tout du cabinet
    assert schema_pour(None) is None


def test_la_consigne_decrit_les_champs_du_schema() -> None:
    consigne = champs_attendus(Facture)
    assert "montant_total_fcfa (entier)" in consigne
    assert "Montant total TTC" in consigne  # la description du champ sert de consigne


# --------------------------------------------------------------------- conversion des valeurs


@pytest.mark.parametrize(
    ("brut", "attendu"),
    [
        ("2 000 000 FCFA", 2000000),
        ("2.000.000", 2000000),
        (2000000, 2000000),
        ("deux millions", None),  # aucun chiffre : rien n'est inventé
    ],
)
def test_les_montants_sont_ramenes_a_des_entiers(brut: Any, attendu: int | None) -> None:
    converti = convertir(Facture, {"montant_total_fcfa": brut})
    assert converti.get("montant_total_fcfa") == attendu


@pytest.mark.parametrize("brut", ["2025-08-09", "09/08/2025", "09-08-2025"])
def test_les_deux_ecritures_de_date_sont_acceptees(brut: str) -> None:
    assert convertir(Facture, {"date_acte": brut})["date_acte"] == "2025-08-09"


def test_une_date_illisible_est_ecartee() -> None:
    assert "date_acte" not in convertir(Facture, {"date_acte": "le 9 août"})


def test_une_liste_donnee_comme_texte_est_corrigee() -> None:
    converti = convertir(MiseEnDemeure, {"factures": "FA-2025-978"})
    assert converti["factures"] == ["FA-2025-978"]


def test_les_champs_vides_ne_sont_pas_inventes() -> None:
    assert convertir(Facture, {"numero": "", "emetteur": None, "montant_total_fcfa": "null"}) == {}


# --------------------------------------------------------------------- contrôle des valeurs


def test_un_montant_absent_du_document_est_signale() -> None:
    douteux = champs_douteux({"montant_total_fcfa": 9999999, "numero": "FA-2025-978"}, TEXTE_FACTURE)
    assert douteux == ["montant_total_fcfa"]


def test_un_montant_present_dans_le_document_ne_lest_pas() -> None:
    assert champs_douteux({"montant_total_fcfa": 2000000}, TEXTE_FACTURE) == []


def test_une_date_presente_sous_une_autre_forme_est_acceptee() -> None:
    """Le document écrit « 09/08/2025 », l'extraction renvoie une date : mêmes chiffres."""
    assert champs_douteux({"date_acte": date(2025, 8, 9)}, TEXTE_FACTURE) == []


def test_un_texte_long_est_tronque_par_le_milieu() -> None:
    document = Document(titre="Contrat", sens=SensEchange.ENTRANT, chemin_fichier="x.pdf", format="pdf")
    document.texte = "DEBUT " + ("blabla " * 5000) + " FIN"
    texte = texte_utile(document)
    assert texte.startswith("DEBUT") and texte.endswith("FIN")
    assert "[…]" in texte, "on garde l'en-tête et le dispositif, qui portent l'essentiel"


# --------------------------------------------------------------------- chaîne complète


def test_une_extraction_est_proposee_et_verifiee(
    monkeypatch: pytest.MonkeyPatch, document_facture: int
) -> None:
    modele = ModeleSimule(
        {
            "numero": "FA-2025-978",
            "montant_total_fcfa": "2 000 000 FCFA",
            "destinataire": "Cap-Vert Immobilier SARL",
            "date_acte": "09/08/2025",
            "delai_paiement_jours": 30,
        }
    )
    monkeypatch.setattr("jurismind.extraction.extracteur.modele_chat", lambda *a, **k: modele)

    with Session(get_engine()) as session:
        document = session.get(Document, document_facture)
        assert document is not None
        proposition = extraire(document)

    assert proposition is not None
    assert proposition.schema == "Facture"
    assert proposition.donnees["montant_total_fcfa"] == 2000000
    assert proposition.donnees["date_acte"] == "2025-08-09"
    assert proposition.champs_douteux == []
    assert "FACTURE N° FA-2025-978" in modele.invites[0], "le texte du document est fourni"


def test_une_valeur_inventee_est_marquee_comme_douteuse(
    monkeypatch: pytest.MonkeyPatch, document_facture: int
) -> None:
    modele = ModeleSimule({"numero": "FA-2025-978", "montant_total_fcfa": 7777777})
    monkeypatch.setattr("jurismind.extraction.extracteur.modele_chat", lambda *a, **k: modele)

    with Session(get_engine()) as session:
        document = session.get(Document, document_facture)
        assert document is not None
        proposition = extraire(document)

    assert proposition is not None
    assert proposition.champs_douteux == ["montant_total_fcfa"]


def test_une_reponse_illisible_ne_produit_rien(
    monkeypatch: pytest.MonkeyPatch, document_facture: int
) -> None:
    monkeypatch.setattr(
        "jurismind.extraction.extracteur.modele_chat", lambda *a, **k: ModeleSimule("pas du json")
    )
    with Session(get_engine()) as session:
        document = session.get(Document, document_facture)
        assert document is not None
        assert extraire(document) is None


def test_une_extraction_validee_nest_jamais_ecrasee(
    monkeypatch: pytest.MonkeyPatch, cabinet: Cabinet, document_facture: int
) -> None:
    modele = ModeleSimule({"numero": "FA-2025-978", "montant_total_fcfa": 2000000})
    monkeypatch.setattr("jurismind.extraction.extracteur.modele_chat", lambda *a, **k: modele)

    with Session(get_engine()) as session, session.begin():
        document = session.get(Document, document_facture)
        assert document is not None
        proposition = extraire(document)
        assert proposition is not None
        extraction = enregistrer(session, document, proposition)
        session.flush()
        valider(
            session, extraction, utilisateur_id=cabinet.dieng, corrections={"emetteur": "Sine Services SA"}
        )

    # Une nouvelle campagne d'extraction repasse sur le document…
    with Session(get_engine()) as session, session.begin():
        document = session.get(Document, document_facture)
        assert document is not None
        nouvelle = extraire(document)
        assert nouvelle is not None
        enregistrer(session, document, nouvelle)

    with Session(get_engine()) as session:
        extraction = session.scalars(select(Extraction)).one()
    assert extraction.statut is StatutExtraction.VALIDEE, "la décision de l'avocat fait foi"
    assert extraction.donnees["emetteur"] == "Sine Services SA"
    assert extraction.valide_par_id == cabinet.dieng


def test_la_validation_corrige_et_retire_le_doute(cabinet: Cabinet, document_facture: int) -> None:
    with Session(get_engine()) as session, session.begin():
        extraction = Extraction(
            document_id=document_facture,
            schema="Facture",
            donnees={"montant_total_fcfa": 7777777},
            champs_douteux=["montant_total_fcfa"],
        )
        session.add(extraction)
        session.flush()
        valider(session, extraction, cabinet.dieng, corrections={"montant_total_fcfa": 2000000})

    with Session(get_engine()) as session:
        relue = session.scalars(select(Extraction)).one()
    assert relue.donnees["montant_total_fcfa"] == 2000000
    assert relue.champs_douteux == []
    assert relue.relue


def test_une_extraction_suit_les_droits_de_son_document(cabinet: Cabinet, document_facture: int) -> None:
    with Session(get_engine()) as session, session.begin():
        session.add(Extraction(document_id=document_facture, schema="Facture", donnees={}))

    # Le document de la fixture appartient au dossier de Me Fall.
    with session_utilisateur(cabinet.fall) as session:
        assert session.scalars(select(Extraction)).all()
    with session_utilisateur(cabinet.dieng) as session:
        assert session.scalars(select(Extraction)).all() == []


# --------------------------------------------------------------------- comparaison des valeurs


@pytest.mark.parametrize(
    ("extrait", "attendu"),
    [
        (2000000, 2000000),
        ("2 000 000 FCFA", 2000000),
        ("société Djoloff Distribution GIE", "Djoloff Distribution GIE"),
        ("FA-2025-978", "FA-2025-978"),
    ],
)
def test_les_valeurs_equivalentes_sont_reconnues(extrait: Any, attendu: Any) -> None:
    assert valeurs_equivalentes(extrait, attendu)


def test_une_forme_juridique_perdue_a_locr_ne_compte_pas_pour_une_erreur() -> None:
    """Cas réel : l'OCR a mangé « SARL », le sens reste le même."""
    assert valeurs_equivalentes("société Baobab Télécom", "Baobab Télécom SARL")


def test_une_valeur_differente_nest_pas_reconnue() -> None:
    assert not valeurs_equivalentes(1500000, 2000000)
    assert not valeurs_equivalentes("Sahel Textile GIE", "Djoloff Distribution GIE")
    # Deux sociétés d'un même groupe ne doivent pas être confondues.
    assert not valeurs_equivalentes("Baobab Distribution SARL", "Baobab Télécom SARL")
