"""Preuves que l'isolation fonctionne : chacun ne voit que les dossiers de ses équipes."""

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from jurismind.db.models import Client, Communication, Document, Dossier, Extrait
from jurismind.db.session import get_app_engine, get_engine, session_utilisateur
from tests.conftest import Cabinet


def dossiers_visibles(utilisateur_id: int) -> set[str]:
    with session_utilisateur(utilisateur_id) as session:
        return set(session.scalars(select(Dossier.reference)))


def test_chaque_avocat_ne_voit_que_ses_dossiers(cabinet: Cabinet) -> None:
    assert dossiers_visibles(cabinet.dieng) == {"D2026-0024", "D2026-0025"}
    assert dossiers_visibles(cabinet.fall) == {"D2026-0027"}


def test_un_dossier_est_partage_par_toute_son_equipe(cabinet: Cabinet) -> None:
    assert dossiers_visibles(cabinet.sy) == {"D2026-0024"}


def test_l_administrateur_ne_voit_aucun_dossier(cabinet: Cabinet) -> None:
    assert dossiers_visibles(cabinet.admin) == set()


def test_sans_utilisateur_identifie_rien_n_est_visible(cabinet: Cabinet) -> None:
    with Session(get_app_engine()) as session:
        assert session.scalars(select(Dossier)).all() == []


def test_l_isolation_s_etend_aux_clients_documents_et_extraits(cabinet: Cabinet) -> None:
    with session_utilisateur(cabinet.dieng) as session:
        assert set(session.scalars(select(Client.nom))) == {"Sine Services SA"}
        assert session.scalars(select(Document)).all() == []
        assert session.scalars(select(Extrait)).all() == []

    with session_utilisateur(cabinet.fall) as session:
        assert [d.titre for d in session.scalars(select(Document))] == ["Jugement"]
        assert len(session.scalars(select(Extrait)).all()) == 1


def test_impossible_de_modifier_le_dossier_d_un_autre(cabinet: Cabinet) -> None:
    with session_utilisateur(cabinet.dieng) as session:
        session.execute(update(Dossier).where(Dossier.reference == "D2026-0027").values(intitule="piraté"))

    # Vérification avec la clé propriétaire, qui voit tout : le dossier n'a pas bougé.
    with Session(get_engine()) as session:
        intitule = session.scalar(select(Dossier.intitule).where(Dossier.reference == "D2026-0027"))
    assert intitule == "Dossier D2026-0027"


def test_les_emails_a_trier_sont_visibles_des_avocats_et_assistants(cabinet: Cabinet) -> None:
    def emails_a_trier(utilisateur_id: int) -> int:
        with session_utilisateur(utilisateur_id) as session:
            requete = select(Communication).where(Communication.dossier_id.is_(None))
            return len(session.scalars(requete).all())

    assert emails_a_trier(cabinet.dieng) == 1
    assert emails_a_trier(cabinet.sy) == 1
    assert emails_a_trier(cabinet.admin) == 0


def test_l_utilisateur_ne_reste_pas_colle_a_la_connexion(cabinet: Cabinet) -> None:
    with session_utilisateur(cabinet.dieng) as session:
        assert session.scalars(select(Dossier)).all()

    # La connexion est réutilisée, mais l'étiquette a disparu avec la transaction.
    with Session(get_app_engine()) as session:
        assert session.scalars(select(Dossier)).all() == []
