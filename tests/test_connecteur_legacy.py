"""Le connecteur traduit le vieux logiciel sans laisser passer ses conventions, et reste rejouable."""

from datetime import UTC, date, datetime
from typing import Any

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from jurismind.connectors.legacy import (
    DonneeIllisible,
    choisir_fiche_principale,
    cle_identite,
    convertir_client,
    convertir_communication,
    convertir_dossier,
    pieces_jointes_de,
    regrouper_doublons,
    synchroniser,
    telephone,
    texte,
)
from jurismind.db.models import (
    AliasClient,
    Client,
    Communication,
    Document,
    Dossier,
    StatutDossier,
    TypeClient,
    TypeDossier,
    Utilisateur,
)
from jurismind.db.session import get_engine, get_legacy_engine

SOCIETE: dict[str, Any] = {
    "cli_id": 22,
    "cli_code": "C00022",
    "cli_type": "PM",
    "cli_raison_soc": "SINE SERVICES SA",
    "cli_forme": "SA",
    "cli_nom": None,
    "cli_prenom": None,
    "cli_rccm": "SN-THS-2007-B-97463",
    "cli_ninea": "003846949 3A2",
    "cli_adresse": "Quartier Médina, Thiès",
    "cli_ville": "Thiès",
    "cli_tel": "+221 33 195 40 96",
    "cli_email": "Contact@sine-services-sa.example",
    "cli_dt_crea": date(2019, 3, 4),
    "cli_obs": None,
}
PARTICULIER: dict[str, Any] = {
    **SOCIETE,
    "cli_id": 5,
    "cli_type": "PP",
    "cli_raison_soc": None,
    "cli_forme": None,
    "cli_nom": "CISSÉ",
    "cli_prenom": "Cheikh",
    "cli_rccm": None,
    "cli_ninea": None,
    "cli_email": "   ",
}
DOSSIER: dict[str, Any] = {
    "dos_id": 34,
    "dos_num": "D2026-0024",
    "cli_id": 22,
    "dos_intitule": "Sine Services SA c/ Cap-Vert Immobilier SARL – Recouvrement",
    "dos_type": "CTX",
    "dos_matiere": "RECOUV",
    "dos_statut": "EC",
    "dos_dt_ouv": date(2026, 8, 9),
    "dos_dt_clo": None,
    "dos_juridiction": "Tribunal de commerce hors classe de Dakar",
    "dos_num_rg": None,
    "dos_enjeu": 13750000,
    "dos_confidentiel": "N",
    "dos_resp_av_id": 1,
}


# --------------------------------------------------------------------- nettoyage des valeurs


@pytest.mark.parametrize(
    ("saisie", "attendu"),
    [
        ("+221 33 195 40 96", "+221331954096"),
        ("331954096", "+221331954096"),
        ("00221331954096", "+221331954096"),
        ("33.195.40.96", "+221331954096"),
        ("  ", None),
        (None, None),
        ("12345", None),  # trop court : mieux vaut rien qu'un numéro faux
    ],
)
def test_les_quatre_formats_de_telephone_du_cabinet(saisie: str | None, attendu: str | None) -> None:
    assert telephone(saisie) == attendu


def test_les_chaines_vides_deviennent_none() -> None:
    assert texte("   ") is None
    assert texte("  Sine   Services  ") == "Sine Services"
    assert texte("Cabinet Téranga Avocats", longueur=7) == "Cabinet"


# --------------------------------------------------------------------- traduction des codes


def test_une_societe_est_traduite_sans_code_dorigine() -> None:
    client = convertir_client(SOCIETE)
    assert client.external_id == 22
    assert client.type is TypeClient.SOCIETE
    assert client.nom == "SINE SERVICES SA"
    assert client.ninea == "003846949 3A2"
    assert client.telephone == "+221331954096"
    assert client.email == "contact@sine-services-sa.example"  # les emails sont mis en minuscules


def test_un_particulier_reunit_prenom_et_nom() -> None:
    client = convertir_client(PARTICULIER)
    assert client.type is TypeClient.PARTICULIER
    assert client.nom == "Cheikh CISSÉ"
    assert client.ninea is None and client.forme_juridique is None
    assert client.email is None


def test_un_code_inconnu_arrete_la_synchronisation() -> None:
    with pytest.raises(DonneeIllisible, match="CLI_TYPE"):
        convertir_client({**SOCIETE, "cli_type": "XX"})


def test_un_dossier_clos_sans_date_de_cloture_est_rattrape() -> None:
    dossier = convertir_dossier({**DOSSIER, "dos_statut": "CL", "dos_dt_clo": None})
    assert dossier.statut is StatutDossier.CLOS
    assert dossier.date_cloture == date(2026, 8, 9)  # défaut de saisie fréquent dans legacy

    en_cours = convertir_dossier(DOSSIER)
    assert en_cours.statut is StatutDossier.EN_COURS
    assert en_cours.type is TypeDossier.CONTENTIEUX
    assert en_cours.date_cloture is None


def test_les_destinataires_et_pieces_jointes_entasses_sont_decoupes() -> None:
    ligne = {
        "cor_id": 152,
        "cor_type": "MAIL",
        "cor_sens": "E",
        "cor_date": datetime(2026, 8, 9, 15, tzinfo=UTC),
        "cor_exped": "ndeye.diallo@sine-services-sa.example",
        "cor_dest": "m.dieng@teranga-avocats.example; c.diouf@teranga-avocats.example",
        "cor_objet": "Impayés",
        "cor_corps": "Maître, …",
        "cor_pj": "180;181;182",
    }
    communication = convertir_communication(ligne)
    assert communication.destinataires == [
        "m.dieng@teranga-avocats.example",
        "c.diouf@teranga-avocats.example",
    ]
    assert pieces_jointes_de(ligne) == [180, 181, 182]
    assert pieces_jointes_de({**ligne, "cor_pj": None}) == []


# --------------------------------------------------------------------- doublons


def test_deux_fiches_partageant_le_rccm_sont_le_meme_client() -> None:
    doublon = {**SOCIETE, "cli_id": 42, "cli_raison_soc": "Sine Services", "cli_ninea": None}
    groupes = regrouper_doublons([SOCIETE, doublon])
    assert len(groupes) == 1
    assert 22 in groupes  # on garde la fiche la plus complète


def test_deux_homonymes_ne_sont_jamais_fusionnes() -> None:
    autre_cisse = {**PARTICULIER, "cli_id": 10, "cli_prenom": "Fatou", "cli_tel": "+221 77 111 22 33"}
    assert cle_identite(PARTICULIER) != cle_identite(autre_cisse)
    assert len(regrouper_doublons([PARTICULIER, autre_cisse])) == 2


def test_un_particulier_sans_moyen_de_contact_reste_seul() -> None:
    sans_contact = {**PARTICULIER, "cli_tel": None, "cli_email": None}
    assert cle_identite(sans_contact).startswith("fiche:")


def test_la_fiche_la_plus_complete_est_retenue() -> None:
    pauvre = {**SOCIETE, "cli_id": 90, "cli_ninea": None, "cli_email": None}
    assert choisir_fiche_principale([pauvre, SOCIETE])["cli_id"] == 22


# --------------------------------------------------------------------- synchronisation complète


@pytest.fixture
def base_vide() -> None:
    tables = (
        "journal_audit, taches, extraits, pieces_jointes, communications, documents, parties, "
        "acces_dossiers, dossiers, contacts, alias_clients, clients, utilisateurs"
    )
    with Session(get_engine()) as session, session.begin():
        session.execute(text(f"TRUNCATE {tables} RESTART IDENTITY CASCADE"))


def _compter(session: Session) -> dict[str, int]:
    return {
        modele.__name__: session.scalar(select(func.count()).select_from(modele)) or 0
        for modele in (Utilisateur, Client, Dossier, Document, Communication, AliasClient)
    }


@pytest.mark.usefixtures("base_vide")
def test_la_synchronisation_est_rejouable_sans_creer_de_doublon() -> None:
    premier = synchroniser(source=get_legacy_engine(), cible=get_engine())
    with Session(get_engine()) as session:
        apres_premier = _compter(session)

    second = synchroniser(source=get_legacy_engine(), cible=get_engine())
    with Session(get_engine()) as session:
        apres_second = _compter(session)

    assert apres_premier == apres_second, "la deuxième synchronisation a modifié le nombre de lignes"
    assert premier.crees["clients"] > 0
    assert second.crees.get("clients", 0) == 0, "des clients ont été recréés au lieu d'être mis à jour"
    assert second.mis_a_jour["clients"] == premier.crees["clients"]


@pytest.mark.usefixtures("base_vide")
def test_la_synchronisation_nettoie_les_donnees_du_cabinet() -> None:
    bilan = synchroniser(source=get_legacy_engine(), cible=get_engine())
    assert bilan.doublons_fusionnes > 0

    with Session(get_engine()) as session:
        clients = session.scalars(select(Client)).all()
        assert all(c.telephone is None or c.telephone.startswith("+221") for c in clients)
        # Chaque fiche d'origine, doublon compris, sait à quel client elle correspond.
        alias = session.scalars(select(func.count()).select_from(AliasClient)).one()
        assert alias == len(clients) + bilan.doublons_fusionnes
        # Les emails pas encore classés sont conservés pour l'agent de tri.
        sans_dossier = session.scalars(
            select(func.count()).select_from(Communication).where(Communication.dossier_id.is_(None))
        ).one()
        assert sans_dossier > 0
