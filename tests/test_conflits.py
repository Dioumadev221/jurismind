"""La vérification des conflits d'intérêts.

Deux comportements inhabituels sont testés ici parce qu'ils sont voulus :

- le contrôle **franchit l'isolation** — il doit voir les dossiers des autres avocats, sans
  quoi il manquerait justement les conflits qu'il cherche ;
- il n'en **révèle que le minimum** — le nom du client en cause, mais les références de
  dossiers seulement si le demandeur y a déjà accès.
"""

from datetime import date

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from jurismind.conformite.conflits import (
    Niveau,
    Relation,
    balayer,
    conflits_du_dossier,
    verifier_identite,
)
from jurismind.db.models import (
    Client,
    Dossier,
    EntreeAudit,
    Partie,
    QualitePartie,
    StatutDossier,
)
from jurismind.db.session import get_engine
from tests.conftest import Cabinet


def ajouter_partie(
    reference: str,
    nom: str,
    qualite: QualitePartie = QualitePartie.ADVERSE,
    email: str | None = None,
) -> None:
    with Session(get_engine()) as session, session.begin():
        dossier = session.scalars(select(Dossier).where(Dossier.reference == reference)).one()
        session.add(Partie(dossier_id=dossier.id, qualite=qualite, nom=nom, email=email))


# ------------------------------------------------------------------ identité


def test_un_nom_identique_est_un_conflit_certain(cabinet: Cabinet) -> None:
    conflits = verifier_identite(cabinet.dieng, "Dakar Télécom SARL")
    assert len(conflits) == 1
    assert conflits[0].niveau is Niveau.CERTAIN
    assert conflits[0].motif == "nom_identique"
    assert conflits[0].client == "Dakar Télécom SARL"


def test_une_forme_juridique_differente_demande_une_verification(cabinet: Cabinet) -> None:
    """« Dakar Télécom SA » et « Dakar Télécom SARL » : deux sociétés, ou une saisie négligée ?"""
    conflits = verifier_identite(cabinet.dieng, "Dakar Télécom SA")
    assert len(conflits) == 1
    assert conflits[0].niveau is Niveau.A_VERIFIER
    assert conflits[0].motif == "nom_sans_forme_juridique"
    assert "forme juridique différente" in conflits[0].explication


def test_un_nom_sans_rapport_ne_declenche_rien(cabinet: Cabinet) -> None:
    assert verifier_identite(cabinet.dieng, "Baobab Énergie SUARL") == []


def test_un_mot_generique_commun_ne_suffit_pas(cabinet: Cabinet) -> None:
    """Sinon tout ce qui s'appelle « Services » ou « Distribution » serait signalé."""
    assert verifier_identite(cabinet.dieng, "Atlantique Services SA") == []
    assert verifier_identite(cabinet.dieng, "Dakar Immobilier SARL") == []


def test_une_coordonnee_partagee_identifie_mieux_quun_nom(cabinet: Cabinet) -> None:
    """Deux sociétés peuvent porter le même nom ; elles partagent rarement une adresse."""
    with Session(get_engine()) as session, session.begin():
        client = session.scalars(select(Client).where(Client.nom == "Dakar Télécom SARL")).one()
        client.email = "contact@dakar-telecom.test"
    conflits = verifier_identite(
        cabinet.dieng, "Société Sans Rapport GIE", email="contact@dakar-telecom.test"
    )
    assert len(conflits) == 1
    assert conflits[0].niveau is Niveau.CERTAIN
    assert conflits[0].motif == "coordonnee_commune"


def test_une_casse_ou_un_accent_ne_fait_pas_manquer_un_conflit(cabinet: Cabinet) -> None:
    assert verifier_identite(cabinet.dieng, "DAKAR TELECOM SARL")
    assert verifier_identite(cabinet.dieng, "dakar télécom sarl")


def test_un_nom_vide_ne_declenche_rien(cabinet: Cabinet) -> None:
    assert verifier_identite(cabinet.dieng, "   ") == []
    assert verifier_identite(cabinet.dieng, "SARL") == []  # une forme juridique seule


# ------------------------------------------------------------------ gravité


def test_un_client_avec_un_dossier_ouvert_est_un_client_actuel(cabinet: Cabinet) -> None:
    assert verifier_identite(cabinet.dieng, "Dakar Télécom SARL")[0].relation == Relation.ACTUEL


def test_un_client_dont_tout_est_clos_est_un_ancien_client(cabinet: Cabinet) -> None:
    """Agir contre un ancien client est moins grave, mais reste à vérifier."""
    with Session(get_engine()) as session, session.begin():
        for dossier in session.scalars(
            select(Dossier).join(Client).where(Client.nom == "Dakar Télécom SARL")
        ).all():
            dossier.statut = StatutDossier.CLOS
            dossier.date_cloture = date(2026, 1, 31)
    assert verifier_identite(cabinet.dieng, "Dakar Télécom SARL")[0].relation == Relation.ANCIEN


# ------------------------------------------------------------------ ce qui est révélé


def test_le_controle_voit_les_dossiers_fermes_au_demandeur(cabinet: Cabinet) -> None:
    """Sans cela il manquerait exactement les conflits qu'il doit trouver."""
    conflits = verifier_identite(cabinet.dieng, "Dakar Télécom SARL")
    assert conflits  # D2026-0027 appartient à Me Fall, Me Dieng n'y a pas accès


def test_un_dossier_ferme_est_compte_mais_pas_nomme(cabinet: Cabinet) -> None:
    conflit = verifier_identite(cabinet.dieng, "Dakar Télécom SARL")[0]
    assert conflit.dossiers_visibles == []
    assert conflit.autres_dossiers == 1
    assert "D2026-0027" not in conflit.ligne()


def test_un_dossier_ouvert_au_demandeur_est_nomme(cabinet: Cabinet) -> None:
    conflit = verifier_identite(cabinet.fall, "Dakar Télécom SARL")[0]
    assert conflit.dossiers_visibles == ["D2026-0027"]
    assert conflit.autres_dossiers == 0


# ------------------------------------------------------------------ par dossier et balayage


def test_les_parties_adverses_dun_dossier_sont_verifiees(cabinet: Cabinet) -> None:
    ajouter_partie("D2026-0024", "Dakar Télécom SA")
    intitule, conflits = conflits_du_dossier(cabinet.dieng, "D2026-0024")
    assert intitule
    assert [conflit.client for conflit in conflits] == ["Dakar Télécom SARL"]


def test_le_client_du_dossier_nest_pas_en_conflit_avec_lui_meme(cabinet: Cabinet) -> None:
    """Le dossier D2026-0024 est ouvert pour Sine Services SA : l'y signaler serait absurde."""
    ajouter_partie("D2026-0024", "Sine Services SARL")
    _, conflits = conflits_du_dossier(cabinet.dieng, "D2026-0024")
    assert conflits == []


def test_seules_les_parties_opposees_comptent(cabinet: Cabinet) -> None:
    """Un huissier ou un confrère portant le nom d'un client n'est pas un conflit d'intérêts."""
    ajouter_partie("D2026-0024", "Dakar Télécom SARL", QualitePartie.HUISSIER)
    _, conflits = conflits_du_dossier(cabinet.dieng, "D2026-0024")
    assert conflits == []


def test_un_dossier_inconnu_est_signale(cabinet: Cabinet) -> None:
    with pytest.raises(LookupError):
        conflits_du_dossier(cabinet.dieng, "D1999-0001")


def test_le_balayage_rend_le_dossier_qui_porte_le_conflit(cabinet: Cabinet) -> None:
    ajouter_partie("D2026-0025", "Dakar Télécom SA")
    resultats = balayer(cabinet.dieng)
    assert [(reference, conflit.client) for reference, conflit in resultats] == [
        ("D2026-0025", "Dakar Télécom SARL")
    ]


def test_un_cabinet_sans_collision_ne_signale_rien(cabinet: Cabinet) -> None:
    ajouter_partie("D2026-0024", "Casamance Pharma SARL")
    assert balayer(cabinet.dieng) == []


# ------------------------------------------------------------------ traçabilité


def test_chaque_verification_est_inscrite_au_journal(cabinet: Cabinet) -> None:
    """Un contrôle qui franchit l'isolation doit laisser une trace de qui l'a demandé."""
    verifier_identite(cabinet.sy, "Dakar Télécom SARL")
    with Session(get_engine()) as session:
        entree = session.scalars(select(EntreeAudit).order_by(EntreeAudit.id.desc())).first()
    assert entree is not None
    assert entree.action == "conflits_verification"
    assert entree.utilisateur_id == cabinet.sy
    assert entree.details["conflits"] == 1
