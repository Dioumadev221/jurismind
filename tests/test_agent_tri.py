"""L'agent de tri du courrier : rattacher sans se tromper, n'agir qu'après un oui.

Trois choses se jouent ici. Un email mal rattaché va dans le dossier d'un autre client :
c'est une fuite. Une relance envoyée à tort sort du cabinet : elle ne se reprend pas. Et une
tâche créée deux fois dans le CRM, c'est le CRM qui devient faux. Les tests portent donc sur
les indices (jamais le modèle), sur l'exigence d'un oui humain, et sur ce qui se passe quand
le CRM ne répond pas.
"""

import json
from datetime import UTC, date, datetime
from typing import Any, cast

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from jurismind.agents.indices import (
    Priorite,
    candidats,
    echeance_relance,
    priorite,
    retenir,
    societe_de,
)
from jurismind.agents.propositions import (
    DejaTranchee,
    PropositionIntrouvable,
    a_trancher,
    appliquer,
    enregistrer,
    rejeter,
    valider,
)
from jurismind.agents.tri import mettre_en_lettre, trier, trier_un
from jurismind.connectors.crm import ApiCrm, CrmIndisponible
from jurismind.db.models import (
    Canal,
    Client,
    Communication,
    Confiance,
    Contact,
    Dossier,
    EntreeAudit,
    Extrait,
    Partie,
    Proposition,
    QualitePartie,
    SensEchange,
    StatutProposition,
    TypeProposition,
)
from jurismind.db.session import get_engine, session_utilisateur
from tests.conftest import Cabinet

DIMENSION = 1024


class ModeleScenario:
    """Répond une chose différente à chaque appel : résumé, puis brouillon."""

    def __init__(self, *reponses: Any) -> None:
        self.reponses = [r if isinstance(r, str) else json.dumps(r) for r in reponses]
        self.invites: list[str] = []

    def invoke(self, invite: str) -> Any:
        self.invites.append(invite)
        brut = self.reponses[min(len(self.invites) - 1, len(self.reponses) - 1)]
        return type("Message", (), {"content": brut})()


def scenario(
    resume: str = "Le confrère annonce une opposition.", brouillon: str = "Bien reçu."
) -> ModeleScenario:
    return ModeleScenario({"resume": resume}, {"brouillon": brouillon})


def brancher(monkeypatch: pytest.MonkeyPatch, modele: Any) -> None:
    monkeypatch.setattr("jurismind.agents.tri.modele_chat", lambda *a, **k: modele)


class CrmSimule:
    """Un CRM qui répond, et qui note ce qu'on lui a demandé d'écrire."""

    def __init__(self, comptes: list[dict[str, Any]] | None = None) -> None:
        self.comptes = (
            comptes if comptes is not None else [{"id": "ACC-1", "name": "Casamance Services SARL"}]
        )
        self.ecrits: list[tuple[str, dict[str, Any]]] = []

    def lister(self, ressource: str, taille_page: int = 100) -> Any:
        return iter(self.comptes if ressource == "accounts" else [])

    def post(self, ressource: str, charge: dict[str, Any]) -> dict[str, Any]:
        self.ecrits.append((ressource, charge))
        return {"id": f"TSK-{len(self.ecrits):05d}", **charge}


class CrmMuet(CrmSimule):
    """Un CRM injoignable : c'est l'état normal un jour sur cent."""

    def post(self, ressource: str, charge: dict[str, Any]) -> dict[str, Any]:
        raise CrmIndisponible("tasks : 4 tentatives sans succès")


@pytest.fixture
def boite(cabinet: Cabinet) -> dict[str, int]:
    """Deux dossiers du même client avec des adversaires qui partagent un mot, et du courrier."""
    with Session(get_engine()) as session, session.begin():
        d24, d25 = session.scalars(
            select(Dossier)
            .where(Dossier.reference.in_(["D2026-0024", "D2026-0025"]))
            .order_by(Dossier.reference)
        ).all()
        d27 = session.scalars(select(Dossier).where(Dossier.reference == "D2026-0027")).one()
        d24.numero_rg = "RG n° 279/2026"
        sine = session.get(Client, d24.client_id)
        assert sine is not None

        session.add_all(
            [
                # « Immobilier » est commun aux deux adversaires : il ne distingue rien.
                Partie(dossier_id=d24.id, qualite=QualitePartie.ADVERSE, nom="Cap-Vert Immobilier SARL"),
                Partie(dossier_id=d25.id, qualite=QualitePartie.ADVERSE, nom="Baobab Immobilier SARL"),
                Partie(
                    dossier_id=d24.id,
                    qualite=QualitePartie.AVOCAT_ADVERSE,
                    nom="Me Binta Diop",
                    email="binta@barreau.test",
                ),
                Contact(client_id=sine.id, nom="Diallo", prenom="Ndeye", email="ndeye@sine.test"),
                Contact(client_id=d27.client_id, nom="Ba", prenom="Omar", email="omar@dakar-telecom.test"),
            ]
        )

        def email(expediteur: str, objet: str, corps: str = "Bonjour.") -> Communication:
            return Communication(
                dossier_id=None,
                canal=Canal.EMAIL,
                sens=SensEchange.ENTRANT,
                date_echange=datetime(2026, 9, 25, 9, tzinfo=UTC),
                expediteur=expediteur,
                objet=objet,
                corps=corps,
            )

        courrier = {
            "reference": email("tiers@ailleurs.test", "Point sur D2026-0024"),
            "numero": email("greffe@tribunal.test", "Affaire n° 279/2026", "Convocation."),
            "confrere": email(
                "binta@barreau.test",
                "Ouest Africa c/ Dakar Distribution",
                "Je suis constitué et forme opposition.",
            ),
            "adverse_nomme": email("ndeye@sine.test", "Loyers impayés – Baobab Immobilier SARL"),
            "mot_generique": email("ndeye@sine.test", "Point sur le local immobilier"),
            "autre_client": email("omar@dakar-telecom.test", "Question sur notre dossier"),
            "prospect": email(
                "lamine@casamance-services-sarl.test",
                "Demande de rendez-vous",
                "Nous envisageons de créer une filiale.",
            ),
        }
        session.add_all(list(courrier.values()))
        session.flush()
        return {nom: int(echange.id) for nom, echange in courrier.items()} | {
            "d24": int(d24.id),
            "d25": int(d25.id),
            "d27": int(d27.id),
        }


def _echange(session: Session, identifiant: int) -> Communication:
    echange = session.get(Communication, identifiant)
    assert echange is not None
    return echange


# ------------------------------------------------------------------ les indices


def test_une_reference_citee_designe_le_dossier(cabinet: Cabinet, boite: dict[str, int]) -> None:
    with session_utilisateur(cabinet.dieng) as session:
        trouves = candidats(session, _echange(session, boite["reference"]))
    assert [(c.indice, c.reference) for c in trouves] == [("reference_dossier", "D2026-0024")]
    assert trouves[0].confiance is Confiance.HAUTE


def test_un_numero_de_role_cite_designe_le_dossier(cabinet: Cabinet, boite: dict[str, int]) -> None:
    with session_utilisateur(cabinet.dieng) as session:
        trouves = candidats(session, _echange(session, boite["numero"]))
    assert ("numero_role", "D2026-0024") in [(c.indice, c.reference) for c in trouves]


def test_un_expediteur_partie_au_dossier_le_designe(cabinet: Cabinet, boite: dict[str, int]) -> None:
    with session_utilisateur(cabinet.dieng) as session:
        garde = retenir(candidats(session, _echange(session, boite["confrere"])))
    assert garde is not None
    assert garde.indice == "partie_au_dossier"
    assert garde.reference == "D2026-0024"


def test_ladversaire_nomme_designe_le_bon_dossier(cabinet: Cabinet, boite: dict[str, int]) -> None:
    """« Baobab » est propre au dossier D2026-0025 : il tranche."""
    with session_utilisateur(cabinet.dieng) as session:
        garde = retenir(candidats(session, _echange(session, boite["adverse_nomme"])))
    assert garde is not None
    assert garde.reference == "D2026-0025"
    assert garde.indice == "contact_et_adverse"


def test_un_mot_partage_par_deux_adversaires_ne_rattache_rien(
    cabinet: Cabinet, boite: dict[str, int]
) -> None:
    """« Immobilier » est dans les deux noms : s'y fier rattachait l'email aux deux dossiers."""
    with session_utilisateur(cabinet.dieng) as session:
        trouves = candidats(session, _echange(session, boite["mot_generique"]))
    assert [c for c in trouves if c.indice == "contact_et_adverse"] == []
    assert retenir(trouves) is None


def test_deux_indices_de_meme_force_qui_se_contredisent_ne_donnent_rien() -> None:
    from jurismind.agents.indices import Candidat

    trouves = [
        Candidat(1, "D2026-0001", "reference_dossier", Confiance.HAUTE),
        Candidat(2, "D2026-0002", "reference_dossier", Confiance.HAUTE),
    ]
    assert retenir(trouves) is None


def test_un_indice_fort_lemporte_sur_un_indice_moyen() -> None:
    from jurismind.agents.indices import Candidat

    trouves = [
        Candidat(1, "D2026-0001", "reference_dossier", Confiance.HAUTE),
        Candidat(2, "D2026-0002", "numero_role", Confiance.MOYENNE),
    ]
    garde = retenir(trouves)
    assert garde is not None
    assert garde.dossier_id == 1


def test_le_rattachement_sarrete_aux_dossiers_que_lon_voit(cabinet: Cabinet, boite: dict[str, int]) -> None:
    """Le contact de Dakar Télécom écrit : Me Fall voit son dossier, Me Dieng non."""
    with session_utilisateur(cabinet.fall) as session:
        garde = retenir(candidats(session, _echange(session, boite["autre_client"])))
    assert garde is not None
    assert garde.reference == "D2026-0027"
    with session_utilisateur(cabinet.dieng) as session:
        assert retenir(candidats(session, _echange(session, boite["autre_client"]))) is None


def test_un_prospect_ne_donne_aucun_candidat(cabinet: Cabinet, boite: dict[str, int]) -> None:
    with session_utilisateur(cabinet.dieng) as session:
        assert candidats(session, _echange(session, boite["prospect"])) == []


# ------------------------------------------------------------------ la priorité


def test_un_mot_de_procedure_rend_lechange_urgent(cabinet: Cabinet, boite: dict[str, int]) -> None:
    with session_utilisateur(cabinet.dieng) as session:
        echange = _echange(session, boite["confrere"])
        niveau, pourquoi = priorite(session, echange, retenir(candidats(session, echange)))
    assert niveau is Priorite.HAUTE
    assert "opposition" in pourquoi


def test_un_echange_sur_un_dossier_en_cours_est_moyen(cabinet: Cabinet, boite: dict[str, int]) -> None:
    with session_utilisateur(cabinet.dieng) as session:
        echange = _echange(session, boite["adverse_nomme"])
        niveau, _ = priorite(session, echange, retenir(candidats(session, echange)))
    assert niveau is Priorite.MOYENNE


def test_un_echange_sans_dossier_est_de_basse_priorite(cabinet: Cabinet, boite: dict[str, int]) -> None:
    with session_utilisateur(cabinet.dieng) as session:
        niveau, _ = priorite(session, _echange(session, boite["prospect"]), None)
    assert niveau is Priorite.BASSE


def test_la_societe_se_devine_depuis_le_domaine() -> None:
    assert societe_de("lamine@casamance-services-sarl.example") == "Casamance Services SARL"
    assert societe_de("x@ouest-africa-btp-sa.example") == "Ouest Africa BTP SA"
    assert societe_de("sans-arobase") is None
    assert societe_de(None) is None


def test_lecheance_de_relance_laisse_deux_jours() -> None:
    assert echeance_relance(date(2026, 10, 6)) == date(2026, 10, 8)


# ------------------------------------------------------------------ le cycle des propositions


def test_une_proposition_sans_fondement_est_refusee(cabinet: Cabinet, boite: dict[str, int]) -> None:
    """Une proposition qui ne dit pas sur quoi elle se fonde n'est pas une proposition."""
    with session_utilisateur(cabinet.dieng) as session, pytest.raises(ValueError):
        enregistrer(
            session,
            TypeProposition.RATTACHEMENT,
            titre="Rattacher",
            justification="   ",
            confiance=Confiance.HAUTE,
        )


def test_valider_un_rattachement_deplace_lechange_et_ses_extraits(
    cabinet: Cabinet, boite: dict[str, int]
) -> None:
    with Session(get_engine()) as session, session.begin():
        session.add(
            Extrait(
                communication_id=boite["adverse_nomme"],
                document_id=None,
                dossier_id=None,
                position=0,
                contenu="Le locataire ne paie plus.",
                embedding=[1.0] + [0.0] * (DIMENSION - 1),
            )
        )
    with session_utilisateur(cabinet.dieng) as session:
        proposition = enregistrer(
            session,
            TypeProposition.RATTACHEMENT,
            titre="Rattacher",
            justification="l'adversaire est nommé",
            confiance=Confiance.HAUTE,
            communication_id=boite["adverse_nomme"],
            dossier_id=boite["d25"],
        )
        tranchee = valider(session, proposition.id, cabinet.dieng)
        assert tranchee.statut is StatutProposition.APPLIQUEE
        assert tranchee.decide_par_id == cabinet.dieng
        assert tranchee.decide_le is not None

    with Session(get_engine()) as session:
        echange = _echange(session, boite["adverse_nomme"])
        extrait = session.scalars(
            select(Extrait).where(Extrait.communication_id == boite["adverse_nomme"])
        ).one()
    assert echange.dossier_id == boite["d25"]
    # Sans cela, la recherche ne retrouverait pas l'email dans le dossier.
    assert extrait.dossier_id == boite["d25"]


def test_on_ne_tranche_pas_deux_fois(cabinet: Cabinet, boite: dict[str, int]) -> None:
    with session_utilisateur(cabinet.dieng) as session:
        proposition = enregistrer(
            session,
            TypeProposition.RATTACHEMENT,
            titre="Rattacher",
            justification="référence citée",
            confiance=Confiance.HAUTE,
            communication_id=boite["reference"],
            dossier_id=boite["d24"],
        )
        valider(session, proposition.id, cabinet.dieng)
        with pytest.raises(DejaTranchee):
            valider(session, proposition.id, cabinet.sy)


def test_rejeter_ne_produit_aucun_effet(cabinet: Cabinet, boite: dict[str, int]) -> None:
    with session_utilisateur(cabinet.dieng) as session:
        proposition = enregistrer(
            session,
            TypeProposition.RATTACHEMENT,
            titre="Rattacher",
            justification="référence citée",
            confiance=Confiance.HAUTE,
            communication_id=boite["reference"],
            dossier_id=boite["d24"],
        )
        tranchee = rejeter(session, proposition.id, cabinet.dieng, "mauvais dossier")
    assert tranchee.statut is StatutProposition.REJETEE
    assert tranchee.donnees["motif_du_rejet"] == "mauvais dossier"
    with Session(get_engine()) as session:
        assert _echange(session, boite["reference"]).dossier_id is None


def test_un_brouillon_valide_nest_pas_envoye(cabinet: Cabinet, boite: dict[str, int]) -> None:
    """JurisMind n'envoie rien : un brouillon validé est approuvé, c'est un humain qui l'envoie."""
    with session_utilisateur(cabinet.dieng) as session:
        proposition = enregistrer(
            session,
            TypeProposition.BROUILLON,
            titre="Réponse",
            justification="accusé de réception",
            confiance=Confiance.MOYENNE,
            communication_id=boite["prospect"],
            contenu="Bien reçu.",
        )
        tranchee = valider(session, proposition.id, cabinet.dieng)
    assert tranchee.statut is StatutProposition.APPLIQUEE
    with Session(get_engine()) as session:
        # Aucun échange sortant n'a été créé.
        sortants = session.scalars(
            select(Communication).where(Communication.sens == SensEchange.SORTANT)
        ).all()
    assert sortants == []


def _proposition_crm(session: Session, boite: dict[str, int], societe: str) -> Proposition:
    return enregistrer(
        session,
        TypeProposition.TACHE_CRM,
        titre=f"Rappeler {societe}",
        justification="aucun dossier ne correspond",
        confiance=Confiance.MOYENNE,
        communication_id=boite["prospect"],
        donnees={"societe": societe, "echeance": "2026-10-08"},
    )


def test_une_tache_crm_validee_est_creee_dans_le_crm(cabinet: Cabinet, boite: dict[str, int]) -> None:
    crm = CrmSimule()
    with session_utilisateur(cabinet.dieng) as session:
        proposition = _proposition_crm(session, boite, "Casamance Services SARL")
        tranchee = valider(session, proposition.id, cabinet.dieng, api=cast(ApiCrm, crm))

    assert tranchee.statut is StatutProposition.APPLIQUEE
    assert tranchee.donnees["crm_task_id"] == "TSK-00001"
    ressource, charge = crm.ecrits[0]
    assert ressource == "tasks"
    assert charge["account_id"] == "ACC-1"
    assert charge["due_date"] == "2026-10-08"
    # Le CRM saura qui a autorisé la tâche.
    assert charge["owner"] == "m.dieng@test"


def test_un_crm_injoignable_laisse_la_proposition_rejouable(cabinet: Cabinet, boite: dict[str, int]) -> None:
    """Validée mais non appliquée : la décision humaine n'est pas perdue."""
    with session_utilisateur(cabinet.dieng) as session:
        proposition = _proposition_crm(session, boite, "Casamance Services SARL")
        echouee = valider(session, proposition.id, cabinet.dieng, api=cast(ApiCrm, CrmMuet()))
        assert echouee.statut is StatutProposition.ECHOUEE
        assert "tentatives" in (echouee.erreur or "")

        # Le CRM est revenu : on rejoue, sans redemander l'autorisation.
        reussie = appliquer(session, echouee.id, api=cast(ApiCrm, CrmSimule()))
    assert reussie.statut is StatutProposition.APPLIQUEE
    assert reussie.erreur is None


def test_un_compte_crm_introuvable_est_dit_clairement(cabinet: Cabinet, boite: dict[str, int]) -> None:
    with session_utilisateur(cabinet.dieng) as session:
        proposition = _proposition_crm(session, boite, "Société Inconnue SARL")
        echouee = valider(session, proposition.id, cabinet.dieng, api=cast(ApiCrm, CrmSimule()))
    assert echouee.statut is StatutProposition.ECHOUEE
    assert "aucun compte CRM" in (echouee.erreur or "")


def test_une_proposition_qui_vise_le_dossier_dautrui_est_invisible(
    cabinet: Cabinet, boite: dict[str, int]
) -> None:
    with session_utilisateur(cabinet.dieng) as session:
        proposition = enregistrer(
            session,
            TypeProposition.RATTACHEMENT,
            titre="Rattacher",
            justification="référence citée",
            confiance=Confiance.HAUTE,
            communication_id=boite["reference"],
            dossier_id=boite["d24"],
        )
        identifiant = proposition.id
    with session_utilisateur(cabinet.fall) as session, pytest.raises(PropositionIntrouvable):
        valider(session, identifiant, cabinet.fall)


def test_une_proposition_sans_dossier_est_vue_du_cabinet_mais_pas_de_ladmin(
    cabinet: Cabinet, boite: dict[str, int]
) -> None:
    with session_utilisateur(cabinet.dieng) as session:
        _proposition_crm(session, boite, "Casamance Services SARL")
    for identifiant, attendu in ((cabinet.dieng, 1), (cabinet.sy, 1), (cabinet.admin, 0)):
        with session_utilisateur(identifiant) as session:
            assert len(a_trancher(session)) == attendu


def test_les_propositions_les_plus_sures_viennent_en_premier(cabinet: Cabinet, boite: dict[str, int]) -> None:
    with session_utilisateur(cabinet.dieng) as session:
        _proposition_crm(session, boite, "Casamance Services SARL")
        enregistrer(
            session,
            TypeProposition.RATTACHEMENT,
            titre="Rattacher",
            justification="référence citée",
            confiance=Confiance.HAUTE,
            communication_id=boite["reference"],
            dossier_id=boite["d24"],
        )
        attente = a_trancher(session)
    assert [str(proposition.confiance) for proposition in attente] == ["haute", "moyenne"]


# ------------------------------------------------------------------ l'agent


def test_un_email_rattachable_donne_un_rattachement_et_un_brouillon(
    monkeypatch: pytest.MonkeyPatch, cabinet: Cabinet, boite: dict[str, int]
) -> None:
    brancher(monkeypatch, scenario())
    with session_utilisateur(cabinet.dieng) as session:
        tri = trier_un(session, cabinet.dieng, boite["confrere"])
        assert tri is not None
        types = [
            str(session.get(Proposition, identifiant).type)  # type: ignore[union-attr]
            for identifiant in tri.propositions
        ]
    assert tri.dossier == "D2026-0024"
    assert tri.priorite == "haute"
    assert tri.qualite == "confrère"
    assert types == ["rattachement", "brouillon"]


def test_un_email_de_prospect_donne_un_brouillon_et_une_tache(
    monkeypatch: pytest.MonkeyPatch, cabinet: Cabinet, boite: dict[str, int]
) -> None:
    brancher(monkeypatch, scenario(resume="Une société demande un rendez-vous."))
    with session_utilisateur(cabinet.dieng) as session:
        tri = trier_un(session, cabinet.dieng, boite["prospect"])
        assert tri is not None
        propositions = [session.get(Proposition, identifiant) for identifiant in tri.propositions]
        types = [str(proposition.type) for proposition in propositions if proposition]
        tache = next(p for p in propositions if p and p.type is TypeProposition.TACHE_CRM)
        societe = tache.donnees["societe"]
    assert tri.dossier is None
    assert types == ["brouillon", "tache_crm"]
    assert societe == "Casamance Services SARL"


def test_un_brouillon_qui_annonce_un_chiffre_est_ecarte(
    monkeypatch: pytest.MonkeyPatch, cabinet: Cabinet, boite: dict[str, int]
) -> None:
    """Un accusé de réception n'annonce ni montant ni délai : s'il en avance un, on ne le propose pas."""
    brancher(
        monkeypatch,
        ModeleScenario(
            {"resume": "Un prospect demande un rendez-vous."},
            {"brouillon": "Bien reçu, nous vous répondrons sous 48 heures."},
        ),
    )
    with session_utilisateur(cabinet.dieng) as session:
        tri = trier_un(session, cabinet.dieng, boite["prospect"])
        assert tri is not None
        types = [
            str(session.get(Proposition, identifiant).type)  # type: ignore[union-attr]
            for identifiant in tri.propositions
        ]
    assert tri.brouillon == ""
    assert types == ["tache_crm"]


def test_rejouer_le_tri_ne_redepose_pas_les_memes_propositions(
    monkeypatch: pytest.MonkeyPatch, cabinet: Cabinet, boite: dict[str, int]
) -> None:
    brancher(monkeypatch, scenario())
    with session_utilisateur(cabinet.dieng) as session:
        premier = trier_un(session, cabinet.dieng, boite["confrere"])
        second = trier_un(session, cabinet.dieng, boite["confrere"])
    assert premier is not None and second is not None
    assert premier.propositions
    assert second.propositions == []


def test_le_tri_complet_classe_les_urgences_en_premier(
    monkeypatch: pytest.MonkeyPatch, cabinet: Cabinet, boite: dict[str, int]
) -> None:
    brancher(monkeypatch, scenario())
    with session_utilisateur(cabinet.dieng) as session:
        reponse = trier(session, cabinet.dieng, limite=20)
    priorites = [tri["priorite"] for tri in reponse.donnees["tris"]]
    assert priorites.index("haute") < priorites.index("basse")
    assert reponse.donnees["propositions_deposees"] > 0


def test_chaque_tri_est_journalise(
    monkeypatch: pytest.MonkeyPatch, cabinet: Cabinet, boite: dict[str, int]
) -> None:
    brancher(monkeypatch, scenario())
    with session_utilisateur(cabinet.dieng) as session:
        trier_un(session, cabinet.dieng, boite["confrere"])

    with Session(get_engine()) as session:
        entree = session.scalars(select(EntreeAudit).order_by(EntreeAudit.id.desc())).first()
    assert entree is not None
    assert entree.action == "agent_tri_courrier"
    assert entree.details["dossier_propose"] == "D2026-0024"
    assert entree.details["priorite"] == "haute"


# ------------------------------------------------------------------ la mise en lettre


def test_un_confrere_est_salue_comme_un_confrere() -> None:
    lettre = mettre_en_lettre("Votre message est bien reçu.", "confrère")
    assert lettre.startswith("Mon cher confrère,")
    assert lettre.endswith("Bien confraternellement,")


def test_un_client_recoit_une_formule_neutre() -> None:
    """La base ne porte pas de civilité : nommer l'interlocuteur serait deviner son genre."""
    lettre = mettre_en_lettre("Nous reviendrons vers vous.", "client")
    assert lettre.startswith("Madame, Monsieur,")
    assert "Monsieur Diallo" not in lettre


def test_une_qualite_inconnue_retombe_sur_la_formule_neutre() -> None:
    assert mettre_en_lettre("Bien reçu.", "huissier-stagiaire").startswith("Madame, Monsieur,")


def test_un_corps_vide_ne_donne_pas_une_lettre_de_politesses() -> None:
    """Sans corps rédigé, il n'y a pas de brouillon — seulement un appel et une politesse."""
    assert mettre_en_lettre("", "client") == ""
    assert mettre_en_lettre("   ", "confrère") == ""
