"""Le journal d'audit : chacun y inscrit ses actions, personne ne l'efface, l'admin lit tout."""

import pytest
from sqlalchemy import delete, select, update
from sqlalchemy.exc import ProgrammingError

from jurismind.db.models import EntreeAudit
from jurismind.db.session import session_utilisateur
from tests.conftest import Cabinet


def journaliser(utilisateur_id: int, action: str) -> None:
    with session_utilisateur(utilisateur_id) as session:
        session.add(EntreeAudit(utilisateur_id=utilisateur_id, action=action))


def actions_visibles(utilisateur_id: int) -> list[str]:
    with session_utilisateur(utilisateur_id) as session:
        return list(session.scalars(select(EntreeAudit.action).order_by(EntreeAudit.id)))


def test_l_administrateur_lit_tout_le_journal(cabinet: Cabinet) -> None:
    journaliser(cabinet.dieng, "question_ia")
    journaliser(cabinet.fall, "analyse_document")
    assert actions_visibles(cabinet.admin) == ["question_ia", "analyse_document"]


def test_chacun_ne_voit_que_ses_propres_actions(cabinet: Cabinet) -> None:
    journaliser(cabinet.dieng, "question_ia")
    journaliser(cabinet.fall, "analyse_document")
    assert actions_visibles(cabinet.dieng) == ["question_ia"]


def test_personne_ne_peut_ecrire_au_nom_d_un_autre(cabinet: Cabinet) -> None:
    with pytest.raises(ProgrammingError), session_utilisateur(cabinet.dieng) as session:
        session.add(EntreeAudit(utilisateur_id=cabinet.fall, action="question_ia"))
        session.flush()


def test_le_journal_ne_peut_etre_ni_modifie_ni_efface(cabinet: Cabinet) -> None:
    journaliser(cabinet.dieng, "question_ia")
    with pytest.raises(ProgrammingError), session_utilisateur(cabinet.admin) as session:
        session.execute(update(EntreeAudit).values(action="modifié"))
    with pytest.raises(ProgrammingError), session_utilisateur(cabinet.admin) as session:
        session.execute(delete(EntreeAudit))
