"""L'agent d'intelligence client : faits calculés, droits respectés, rien d'inventé.

Le modèle est simulé. Ce qu'on vérifie, c'est que les points d'attention sortent d'une règle
appliquée aux données — donc qu'on peut toujours remonter à la date ou au statut qui les a
déclenchés — et qu'un avocat ne voit du client que les dossiers qui lui sont ouverts.

La date du jour est toujours passée explicitement : une règle qui dépend du calendrier doit
pouvoir être rejouée à l'identique dans six mois.
"""

import json
from datetime import UTC, date, datetime
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from jurismind.agents.client import Intention, assister, deviner_intention
from jurismind.agents.outils import (
    derniers_echanges,
    dossiers_du_client,
    fiche_client,
    montant_lisible,
    points_attention,
    trouver_client,
)
from jurismind.db.models import (
    AccesDossier,
    Canal,
    Client,
    Communication,
    Document,
    Dossier,
    ElementCrm,
    EntreeAudit,
    Extraction,
    SensEchange,
    StatutDossier,
    StatutExtraction,
    TypeClient,
    TypeDossier,
    TypeElementCrm,
)
from jurismind.db.session import get_engine, session_utilisateur
from jurismind.rag.reponse import Citation, Reponse
from tests.conftest import Cabinet

AUJOURDHUI = date(2026, 10, 2)
DIMENSION = 1024


class ModeleSimule:
    def __init__(self, reponse: Any) -> None:
        self.reponse = reponse if isinstance(reponse, str) else json.dumps(reponse)
        self.invites: list[str] = []

    def invoke(self, invite: str) -> Any:
        self.invites.append(invite)
        return type("Message", (), {"content": self.reponse})()


class ModeleInterdit:
    def invoke(self, invite: str) -> Any:
        raise AssertionError("le modèle ne doit pas être appelé ici")


def brancher(monkeypatch: pytest.MonkeyPatch, modele: Any) -> None:
    monkeypatch.setattr("jurismind.agents.client.modele_chat", lambda *a, **k: modele)


@pytest.fixture
def client_sine(cabinet: Cabinet) -> int:
    """Le client de Me Dieng, avec deux dossiers visibles par lui, un acte et un échange."""
    with Session(get_engine()) as session, session.begin():
        client = session.scalars(select(Client).where(Client.nom == "Sine Services SA")).one()
        d24, d25 = session.scalars(
            select(Dossier)
            .where(Dossier.reference.in_(["D2026-0024", "D2026-0025"]))
            .order_by(Dossier.reference)
        ).all()
        d24.enjeu_fcfa = 13_750_000
        d24.juridiction = "Tribunal de commerce de Dakar"
        d25.enjeu_fcfa = 2_000_000

        mise_en_demeure = Document(
            dossier_id=d24.id,
            titre="Mise en demeure",
            sens=SensEchange.SORTANT,
            chemin_fichier="D2026-0024/mise-en-demeure.pdf",
            format="pdf",
            date_document=date(2026, 9, 20),
        )
        echange = Communication(
            dossier_id=d24.id,
            canal=Canal.EMAIL,
            sens=SensEchange.ENTRANT,
            date_echange=datetime(2026, 9, 22, 9, tzinfo=UTC),
            expediteur="ndeye.diallo@sine.example",
            objet="Où en est le recouvrement ?",
            corps="Merci de me tenir informée.",
        )
        session.add_all([mise_en_demeure, echange])
        session.flush()
        session.add(
            Extraction(
                document_id=mise_en_demeure.id,
                schema="mise_en_demeure",
                donnees={
                    "date_acte": "2026-09-20",
                    "montant_reclame_fcfa": 13_750_000,
                    "delai_jours": 15,
                },
                champs_douteux=["montant_reclame_fcfa"],
                statut=StatutExtraction.PROPOSEE,
            )
        )
        return int(client.id)


# ------------------------------------------------------------------ outils de lecture


def test_un_client_se_retrouve_par_son_nom_meme_approximatif(cabinet: Cabinet, client_sine: int) -> None:
    with session_utilisateur(cabinet.dieng) as session:
        assert trouver_client(session, "sine services sa") == client_sine
        assert trouver_client(session, "Sine") == client_sine


def test_un_nom_qui_designe_plusieurs_clients_ne_renvoie_rien(cabinet: Cabinet, client_sine: int) -> None:
    """Mieux vaut demander de préciser que faire le point sur le mauvais client."""
    with Session(get_engine()) as session, session.begin():
        homonyme = Client(nom="Sine Distribution SARL", type=TypeClient.SOCIETE)
        autre = Dossier(
            reference="D2026-0030",
            client=homonyme,
            intitule="Sine Distribution SARL – conseil",
            type=TypeDossier.CONSEIL,
            matiere="SOC",
            statut=StatutDossier.EN_COURS,
            date_ouverture=date(2026, 9, 1),
        )
        session.add(autre)
        session.flush()
        # Sans accès, le deuxième client resterait invisible et le nom ne serait plus ambigu.
        session.add(AccesDossier(dossier_id=autre.id, utilisateur_id=cabinet.dieng))
    with session_utilisateur(cabinet.dieng) as session:
        assert trouver_client(session, "Sine") is None
        assert trouver_client(session, "Sine Services SA") == client_sine


def test_la_fiche_ne_compte_que_les_dossiers_visibles(cabinet: Cabinet, client_sine: int) -> None:
    """Me Dieng voit deux dossiers du client ; l'assistante n'en voit qu'un."""
    with session_utilisateur(cabinet.dieng) as session:
        fiche = fiche_client(session, client_sine)
        assert fiche is not None
        assert fiche["dossiers_visibles"] == 2
        assert fiche["enjeu_total_fcfa"] == 15_750_000
    with session_utilisateur(cabinet.sy) as session:
        fiche = fiche_client(session, client_sine)
        assert fiche is not None
        assert fiche["dossiers_visibles"] == 1
        assert fiche["enjeu_total_fcfa"] == 13_750_000


def test_un_client_dont_on_ne_voit_aucun_dossier_est_invisible(cabinet: Cabinet, client_sine: int) -> None:
    with session_utilisateur(cabinet.fall) as session:
        assert fiche_client(session, client_sine) is None


def test_les_dossiers_portent_leur_dernier_mouvement(cabinet: Cabinet, client_sine: int) -> None:
    with session_utilisateur(cabinet.dieng) as session:
        dossiers = {d["reference"]: d for d in dossiers_du_client(session, client_sine)}
    # L'échange du 22/09 est plus récent que la pièce du 20/09 : c'est lui qui compte.
    assert dossiers["D2026-0024"]["derniere_activite"] == date(2026, 9, 22)
    assert dossiers["D2026-0024"]["responsable"] == "Me Dieng"
    assert dossiers["D2026-0025"]["derniere_activite"] is None


def test_les_echanges_sont_rendus_du_plus_recent_au_plus_ancien(cabinet: Cabinet, client_sine: int) -> None:
    with session_utilisateur(cabinet.dieng) as session:
        echanges = derniers_echanges(session, client_sine)
    assert echanges[0]["dossier"] == "D2026-0024"
    assert echanges[0]["sens"] == "reçu"
    assert echanges[0]["interlocuteur"] == "ndeye.diallo@sine.example"


def test_les_montants_sont_ecrits_comme_dans_un_acte() -> None:
    assert montant_lisible(13_750_000) == "13 750 000"


# ------------------------------------------------------------------ points d'attention


def _libelles(points: list[Any]) -> list[str]:
    return [point.libelle for point in points]


def test_un_delai_qui_echoit_bientot_est_signale(cabinet: Cabinet, client_sine: int) -> None:
    """Mise en demeure du 20/09 + 15 jours : le délai échoit le 05/10, dans 3 jours."""
    with session_utilisateur(cabinet.dieng) as session:
        points = points_attention(session, client_sine, aujourdhui=AUJOURDHUI)
    delai = next(point for point in points if point.libelle.startswith("Délai de la mise en demeure"))
    assert delai.gravite == "haute"
    assert "05/10/2026" in delai.detail
    assert "3 jours" in delai.detail
    assert delai.dossier == "D2026-0024"


def test_un_delai_echu_depuis_longtemps_nest_plus_signale(cabinet: Cabinet, client_sine: int) -> None:
    """Sinon la liste se remplit de délais morts et l'avocat n'y regarde plus."""
    with session_utilisateur(cabinet.dieng) as session:
        points = points_attention(session, client_sine, aujourdhui=date(2027, 6, 1))
    assert not [point for point in points if "Délai" in point.libelle]


def test_un_echange_entrant_sans_reponse_est_signale(cabinet: Cabinet, client_sine: int) -> None:
    with session_utilisateur(cabinet.dieng) as session:
        points = points_attention(session, client_sine, aujourdhui=AUJOURDHUI)
    attente = next(point for point in points if point.libelle.startswith("Dernier échange"))
    assert "10 jours" in attente.detail
    assert attente.dossier == "D2026-0024"


def test_une_reponse_envoyee_eteint_lalerte(cabinet: Cabinet, client_sine: int) -> None:
    """Le dernier échange devient sortant : plus personne n'attend."""
    with Session(get_engine()) as session, session.begin():
        dossier = session.scalars(select(Dossier).where(Dossier.reference == "D2026-0024")).one()
        session.add(
            Communication(
                dossier_id=dossier.id,
                canal=Canal.EMAIL,
                sens=SensEchange.SORTANT,
                date_echange=datetime(2026, 9, 25, 9, tzinfo=UTC),
                expediteur="m.dieng@test",
                destinataires=["ndeye.diallo@sine.example"],
                objet="RE: Où en est le recouvrement ?",
                corps="Voici le point.",
            )
        )
    with session_utilisateur(cabinet.dieng) as session:
        points = points_attention(session, client_sine, aujourdhui=AUJOURDHUI)
    assert not [point for point in points if point.libelle.startswith("Dernier échange")]


def test_un_dossier_sans_mouvement_depuis_longtemps_est_signale(cabinet: Cabinet, client_sine: int) -> None:
    """D2026-0025 est ouvert depuis le 09/08/2026 et n'a jamais rien reçu."""
    with session_utilisateur(cabinet.dieng) as session:
        # Au 02/10 il dort depuis 54 jours : sous le seuil, donc silence.
        assert "Dossier en sommeil" not in _libelles(
            points_attention(session, client_sine, aujourdhui=AUJOURDHUI)
        )
        points = points_attention(session, client_sine, aujourdhui=date(2026, 11, 15))
    sommeil = next(point for point in points if point.libelle == "Dossier en sommeil")
    assert sommeil.dossier == "D2026-0025"
    assert "aucune pièce depuis l'ouverture" in sommeil.detail


def test_un_dossier_clos_nest_pas_signale_comme_endormi(cabinet: Cabinet, client_sine: int) -> None:
    with Session(get_engine()) as session, session.begin():
        dossier = session.scalars(select(Dossier).where(Dossier.reference == "D2026-0025")).one()
        dossier.statut = StatutDossier.CLOS
        dossier.date_cloture = date(2026, 9, 1)
    with session_utilisateur(cabinet.dieng) as session:
        points = points_attention(session, client_sine, aujourdhui=date(2026, 11, 15))
    assert not [point for point in points if point.libelle == "Dossier en sommeil"]


def test_une_valeur_douteuse_non_relue_est_signalee(cabinet: Cabinet, client_sine: int) -> None:
    with session_utilisateur(cabinet.dieng) as session:
        points = points_attention(session, client_sine, aujourdhui=AUJOURDHUI)
    assert "Valeurs extraites à relire" in _libelles(points)


def test_une_extraction_validee_ne_demande_plus_de_relecture(cabinet: Cabinet, client_sine: int) -> None:
    with Session(get_engine()) as session, session.begin():
        extraction = session.scalars(select(Extraction)).one()
        extraction.statut = StatutExtraction.VALIDEE
    with session_utilisateur(cabinet.dieng) as session:
        points = points_attention(session, client_sine, aujourdhui=AUJOURDHUI)
    assert "Valeurs extraites à relire" not in _libelles(points)


def test_le_crm_remonte_les_mandats_en_negociation(cabinet: Cabinet, client_sine: int) -> None:
    with Session(get_engine()) as session, session.begin():
        session.add_all(
            [
                ElementCrm(
                    external_id="OPP-1",
                    client_id=client_sine,
                    type=TypeElementCrm.OPPORTUNITE,
                    titre="Recouvrement de portefeuille",
                    statut="negociation",
                    montant_fcfa=13_500_000,
                ),
                ElementCrm(
                    external_id="OPP-2",
                    client_id=client_sine,
                    type=TypeElementCrm.OPPORTUNITE,
                    titre="Mandat déjà signé",
                    statut="gagnee",
                ),
            ]
        )
    with session_utilisateur(cabinet.dieng) as session:
        points = points_attention(session, client_sine, aujourdhui=AUJOURDHUI)
    mandats = [point for point in points if point.libelle == "Mandat en cours de négociation"]
    assert len(mandats) == 1  # un mandat gagné n'est pas un point d'attention
    assert "13 500 000 FCFA" in mandats[0].detail


def test_les_points_les_plus_graves_viennent_en_premier(cabinet: Cabinet, client_sine: int) -> None:
    with session_utilisateur(cabinet.dieng) as session:
        points = points_attention(session, client_sine, aujourdhui=AUJOURDHUI)
    gravites = [point.gravite for point in points]
    assert gravites == sorted(gravites, key=lambda gravite: gravite != "haute")


def test_un_client_sans_rien_a_signaler_ne_signale_rien(cabinet: Cabinet) -> None:
    """Une liste vide est une information : on ne la remplit pas pour faire riche."""
    with session_utilisateur(cabinet.fall) as session:
        dossier = session.scalars(select(Dossier).where(Dossier.reference == "D2026-0027")).one()
        assert points_attention(session, dossier.client_id, aujourdhui=date(2026, 8, 20)) == []


# ------------------------------------------------------------------ l'agent


def test_la_fiche_ne_derange_jamais_le_modele(
    monkeypatch: pytest.MonkeyPatch, cabinet: Cabinet, client_sine: int
) -> None:
    brancher(monkeypatch, ModeleInterdit())
    with session_utilisateur(cabinet.dieng) as session:
        reponse = assister(session, cabinet.dieng, client_sine, "points d'attention")

    assert reponse.intention == "fiche"
    assert not reponse.abstention
    assert "D2026-0024" in reponse.texte
    assert "13 750 000 FCFA" in reponse.texte
    assert reponse.donnees["points_attention"]


def test_les_demandes_explicites_ne_derangent_pas_le_modele() -> None:
    assert deviner_intention("fais-moi la fiche") is Intention.FICHE
    assert deviner_intention("qu'est-ce qui mérite mon attention ?") is Intention.FICHE
    assert deviner_intention("fais le point sur ce client") is Intention.SYNTHESE
    assert deviner_intention("") is Intention.SYNTHESE
    assert deviner_intention("A-t-il payé la facture FA-2026-988 ?") is None


def test_la_synthese_recoit_les_faits_mais_pas_les_chiffres_a_recopier(
    monkeypatch: pytest.MonkeyPatch, cabinet: Cabinet, client_sine: int
) -> None:
    """Le modèle situe le client ; les montants et les délais sont ajoutés par le code."""
    modele = ModeleSimule({"synthese": "Sine Services SA est en recouvrement contre Cap-Vert."})
    brancher(monkeypatch, modele)
    with session_utilisateur(cabinet.dieng) as session:
        reponse = assister(session, cabinet.dieng, client_sine, "fais le point")

    assert reponse.intention == "synthese"
    assert not reponse.abstention
    invite = modele.invites[0]
    assert "D2026-0024" in invite
    # Les points d'attention ne lui sont pas soumis : il les rattachait au mauvais dossier.
    assert "Délai de la mise en demeure" not in invite
    # Et ils figurent pourtant dans la réponse, avec les enjeux exacts.
    assert "Délai de la mise en demeure" in reponse.texte
    assert "13 750 000 FCFA" in reponse.texte
    assert reponse.donnees["points_attention"]


def test_une_prose_sans_chiffre_nest_pas_rejetee(
    monkeypatch: pytest.MonkeyPatch, cabinet: Cabinet, client_sine: int
) -> None:
    """Un texte qui n'avance aucun chiffre n'a rien à ancrer : il ne doit pas être écarté."""
    brancher(monkeypatch, ModeleSimule({"synthese": "Une société de Dakar suivie en recouvrement."}))
    with session_utilisateur(cabinet.dieng) as session:
        reponse = assister(session, cabinet.dieng, client_sine, "fais le point")
    assert not reponse.abstention


def test_la_cle_du_json_est_toleree_de_travers(
    monkeypatch: pytest.MonkeyPatch, cabinet: Cabinet, client_sine: int
) -> None:
    """`qwen2.5:3b` répond « synthèse » quand on demande « synthese » : la forme, pas le fond."""
    brancher(monkeypatch, ModeleSimule({"synthèse": "Société dakaroise suivie en recouvrement."}))
    with session_utilisateur(cabinet.dieng) as session:
        reponse = assister(session, cabinet.dieng, client_sine, "fais le point")
    assert not reponse.abstention
    assert reponse.texte.startswith("Société dakaroise")


def test_un_montant_absent_des_donnees_fait_abandonner_la_synthese(
    monkeypatch: pytest.MonkeyPatch, cabinet: Cabinet, client_sine: int
) -> None:
    brancher(monkeypatch, ModeleSimule({"synthese": "Le client nous doit 99 000 000 FCFA."}))
    with session_utilisateur(cabinet.dieng) as session:
        reponse = assister(session, cabinet.dieng, client_sine, "fais le point")

    assert reponse.abstention
    assert "99 000 000" not in reponse.texte


def test_la_question_est_bornee_aux_dossiers_du_client(
    monkeypatch: pytest.MonkeyPatch, cabinet: Cabinet, client_sine: int
) -> None:
    brancher(monkeypatch, ModeleInterdit())
    filtres_recus: list[Any] = []

    def repondre_simule(session: Any, question: str, filtres: Any = None, **_: Any) -> Reponse:
        filtres_recus.append(filtres)
        return Reponse(
            texte="Non, la facture reste impayée.",
            citations=[
                Citation(numero=1, reference="Mise en demeure, page 1", extrait_id=1, dossier_id=None)
            ],
            abstention=False,
        )

    monkeypatch.setattr("jurismind.agents.client.repondre", repondre_simule)
    monkeypatch.setattr("jurismind.agents.client.deviner_intention", lambda _: Intention.QUESTION)
    with session_utilisateur(cabinet.dieng) as session:
        reponse = assister(session, cabinet.dieng, client_sine, "La facture est-elle payée ?")

    assert reponse.citations[0]["reference"] == "Mise en demeure, page 1"
    assert filtres_recus[0].client_id == client_sine
    assert filtres_recus[0].dossier_id is None


def test_un_client_dautrui_ne_laisse_rien_filtrer(
    monkeypatch: pytest.MonkeyPatch, cabinet: Cabinet, client_sine: int
) -> None:
    brancher(monkeypatch, ModeleInterdit())
    with session_utilisateur(cabinet.fall) as session:
        reponse = assister(session, cabinet.fall, client_sine, "fais le point")

    assert reponse.abstention
    assert reponse.texte == "Client introuvable."
    assert reponse.donnees["dossiers"] == []


def test_chaque_passage_de_lagent_est_journalise(
    monkeypatch: pytest.MonkeyPatch, cabinet: Cabinet, client_sine: int
) -> None:
    brancher(monkeypatch, ModeleInterdit())
    with session_utilisateur(cabinet.dieng) as session:
        assister(session, cabinet.dieng, client_sine, "fiche")

    with Session(get_engine()) as session:
        entree = session.scalars(select(EntreeAudit).order_by(EntreeAudit.id.desc())).first()
    assert entree is not None
    assert entree.action == "agent_client_fiche"
    assert entree.utilisateur_id == cabinet.dieng
    assert entree.details["client_id"] == client_sine
    assert entree.details["dossiers_vus"] == 2
