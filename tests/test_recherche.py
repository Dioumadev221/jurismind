"""La recherche hybride : le sens, les mots, leur fusion — et les droits d'accès."""

from typing import Any

import pytest
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from jurismind.db.models import Communication, Document, Dossier, Extrait
from jurismind.db.session import get_engine, session_utilisateur
from jurismind.retrieval import Filtres, rechercher
from jurismind.retrieval.recherche import Resultat, fusionner, recherche_plein_texte
from tests.conftest import Cabinet

DIMENSION = 1024


def vecteur(*premieres_valeurs: float) -> list[float]:
    """Un vecteur factice : les premières coordonnées portent le sens, le reste est nul."""
    valeurs = list(premieres_valeurs)
    return valeurs + [0.0] * (DIMENSION - len(valeurs))


@pytest.fixture
def extraits(cabinet: Cabinet) -> dict[str, int]:
    """Trois extraits : deux dans le dossier de Me Dieng, un dans celui de Me Fall."""
    with Session(get_engine()) as session, session.begin():
        dossiers = {d.reference: d for d in session.scalars(select(Dossier))}
        d24, d27 = dossiers["D2026-0024"], dossiers["D2026-0027"]
        document = session.scalars(select(Document)).first()
        assert document is not None
        communication = session.scalars(select(Communication)).first()
        assert communication is not None

        opposition = Extrait(
            dossier_id=d24.id,
            communication_id=communication.id,
            position=0,
            contenu=(
                "Le débiteur dispose d'un délai de quinze jours à compter de la signification "
                "pour former opposition devant la juridiction."
            ),
            embedding=vecteur(1.0, 0.0),
        )
        facture = Extrait(
            dossier_id=d24.id,
            communication_id=communication.id,
            position=1,
            contenu="Facture FA-2025-978 d'un montant de 2 000 000 FCFA, échue et impayée.",
            embedding=vecteur(0.0, 1.0),
        )
        confidentiel = Extrait(
            dossier_id=d27.id,
            document_id=document.id,
            position=0,
            contenu="Le tribunal condamne Dakar Télécom à verser 8 000 000 FCFA.",
            embedding=vecteur(1.0, 0.0),  # aussi proche que l'extrait « opposition »
        )
        session.add_all([opposition, facture, confidentiel])
        session.flush()
        identifiants = {
            "opposition": opposition.id,
            "facture": facture.id,
            "confidentiel": confidentiel.id,
        }
    return identifiants


# --------------------------------------------------------------------- fusion RRF


def _resultat_factice(identifiant: int) -> Any:
    class ExtraitFactice:
        id = identifiant

    return ExtraitFactice()


def test_un_extrait_trouve_par_les_deux_recherches_passe_devant() -> None:
    a, b, c = (_resultat_factice(n) for n in (1, 2, 3))
    resultats = fusionner(vectoriels=[(a, 0.9), (b, 0.8)], textuels=[c, a], limite=3)

    # 1 est dans les deux listes ; 3 est premier « par les mots », donc devant 2 (deuxième
    # « par le sens ») : RRF compare des rangs, pas des scores.
    assert [r.extrait.id for r in resultats] == [1, 3, 2]
    assert resultats[0].trouve_par == "sens + mots"
    assert resultats[0].similarite == pytest.approx(0.9)


def test_un_extrait_trouve_par_les_seuls_mots_na_pas_de_similarite() -> None:
    a, b = (_resultat_factice(n) for n in (1, 2))
    resultats = fusionner(vectoriels=[(a, 0.5)], textuels=[b], limite=2)
    par_identifiant = {r.extrait.id: r for r in resultats}

    assert par_identifiant[2].similarite is None
    assert par_identifiant[2].trouve_par == "mots"


# --------------------------------------------------------------------- recherche réelle


def test_la_recherche_par_le_sens_trouve_sans_mot_commun(extraits: dict[str, int]) -> None:
    # La question « contester une décision » ne partage aucun mot avec l'extrait.
    with Session(get_engine()) as session:
        resultats = rechercher(session, "contester une décision", vecteur=vecteur(1.0, 0.0), limite=1)
    assert resultats[0].extrait.id in {extraits["opposition"], extraits["confidentiel"]}


def test_la_recherche_par_les_mots_trouve_un_numero_exact(extraits: dict[str, int]) -> None:
    with Session(get_engine()) as session:
        trouves = recherche_plein_texte(session, "FA-2025-978", Filtres())
    assert extraits["facture"] in {e.id for e in trouves}


def test_les_filtres_limitent_la_recherche_a_un_dossier(cabinet: Cabinet, extraits: dict[str, int]) -> None:
    with Session(get_engine()) as session:
        dossier = session.scalars(select(Dossier).where(Dossier.reference == "D2026-0027")).one()
        resultats = rechercher(
            session,
            "condamnation",
            filtres=Filtres(dossier_id=dossier.id),
            vecteur=vecteur(1.0, 0.0),
            limite=5,
        )
    trouves = {r.extrait.id for r in resultats}
    assert extraits["confidentiel"] in trouves
    assert extraits["opposition"] not in trouves and extraits["facture"] not in trouves
    assert all(r.extrait.dossier_id == dossier.id for r in resultats)


def test_la_recherche_ne_franchit_jamais_les_droits(cabinet: Cabinet, extraits: dict[str, int]) -> None:
    """Le test le plus important : l'extrait d'un autre avocat n'est même pas lu."""
    with session_utilisateur(cabinet.dieng) as session:
        vus = {r.extrait.id for r in rechercher(session, "condamnation", vecteur=vecteur(1.0, 0.0), limite=5)}
    assert extraits["confidentiel"] not in vus
    assert extraits["opposition"] in vus

    with session_utilisateur(cabinet.fall) as session:
        vus_par_fall = {
            r.extrait.id for r in rechercher(session, "condamnation", vecteur=vecteur(1.0, 0.0), limite=5)
        }
    assert extraits["confidentiel"] in vus_par_fall
    assert extraits["opposition"] not in vus_par_fall, "Me Fall ne doit pas voir le dossier de Me Dieng"


def test_la_reference_dun_resultat_permet_de_citer(extraits: dict[str, int]) -> None:
    with Session(get_engine()) as session:
        extrait = session.get(Extrait, extraits["confidentiel"])
        assert extrait is not None
        resultat = Resultat(extrait=extrait, score=1.0)
        assert "Jugement" in resultat.reference


def test_sans_utilisateur_la_recherche_ne_renvoie_rien(extraits: dict[str, int]) -> None:
    from jurismind.db.session import get_app_engine

    with Session(get_app_engine()) as session:
        session.execute(text("SELECT set_config('app.utilisateur_id', '', true)"))
        assert rechercher(session, "condamnation", vecteur=vecteur(1.0, 0.0), limite=5) == []
