"""L'API REST : qui peut appeler quoi, et ce qui ne filtre pas.

Ce qui se joue ici n'est pas la mise en forme JSON, c'est l'isolation. Chaque requête ouvre
une session **au nom de l'utilisateur du jeton**, donc soumise au RLS : les tests vérifient
qu'une route ne rend rien d'un dossier fermé, et qu'elle répond 404 — pas 403 — pour ne pas
révéler son existence.

Aucun test de ce fichier n'appelle de modèle, et la fixture `sans_ollama` le **garantit**
au lieu de l'espérer : le vecteur de recherche est remplacé par une constante, et toute
tentative d'appeler le modèle de rédaction échoue bruyamment. Sans cela, ces tests passent
sur un poste où Ollama tourne et échouent en intégration continue, ce qui s'est produit.
"""

from datetime import UTC, date, datetime
from typing import Any, cast

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from jurismind.api.main import app
from jurismind.api.securite import creer_jeton, hacher, verifier
from jurismind.db.models import (
    Canal,
    Communication,
    Confiance,
    Document,
    Dossier,
    Extraction,
    Partie,
    Proposition,
    QualitePartie,
    Role,
    SensEchange,
    StatutExtraction,
    StatutProposition,
    TypeProposition,
    Utilisateur,
)
from jurismind.db.session import get_engine
from tests.conftest import Cabinet

# Mots de passe de test, créés ici et nulle part ailleurs.
MOTS_DE_PASSE = {
    "m.dieng@test": "dieng-mot-de-test",
    "a.fall@test": "fall-mot-de-test",
    "c.sy@test": "sy-mot-de-test",
    "admin@test": "admin-mot-de-test",
}


# Modules qui tiennent une référence au modèle de rédaction : les agents l'importent
# dans leur propre espace de noms, donc chacun doit être neutralisé séparément.
MODULES_DE_REDACTION = (
    "jurismind.rag.reponse",
    "jurismind.agents.dossier",
    "jurismind.agents.client",
    "jurismind.agents.analyse",
    "jurismind.agents.tri",
)
DIMENSION = 1024


@pytest.fixture(autouse=True)
def sans_ollama(monkeypatch: pytest.MonkeyPatch) -> None:
    """Coupe l'API de tout service de modèle, pour tous les tests de ce fichier.

    La recherche calcule un vecteur de requête : sans ce remplacement, `/recherche`
    appelle Ollama, et le test ne passe que sur un poste où il tourne. La qualité de la
    recherche est mesurée ailleurs, par le jeu d'évaluation ; ce qu'on teste ici, ce sont
    les droits et les codes de retour.
    """
    monkeypatch.setattr(
        "jurismind.retrieval.recherche.modele_embeddings",
        lambda: type(
            "Embeddings",
            (),
            {"embed_query": staticmethod(lambda _: [1.0] + [0.0] * (DIMENSION - 1))},
        )(),
    )

    def interdit(*args: object, **options: object) -> object:
        raise AssertionError("un test d'API ne doit pas appeler le modèle de rédaction")

    for module in MODULES_DE_REDACTION:
        monkeypatch.setattr(f"{module}.modele_chat", interdit)


@pytest.fixture
def api() -> httpx.Client:
    # `TestClient` est synchrone et expose l'interface de httpx.Client.
    return cast(httpx.Client, TestClient(app))


@pytest.fixture
def comptes(cabinet: Cabinet) -> Cabinet:
    """Donne un mot de passe utilisable aux comptes du mini-cabinet."""
    with Session(get_engine()) as session, session.begin():
        for email, mot_de_passe in MOTS_DE_PASSE.items():
            utilisateur = session.scalars(select(Utilisateur).where(Utilisateur.email == email)).one()
            utilisateur.mot_de_passe_hash = hacher(mot_de_passe)
    return cabinet


def connecter(api: httpx.Client, email: str) -> dict[str, str]:
    reponse = api.post("/connexion", json={"email": email, "mot_de_passe": MOTS_DE_PASSE[email]})
    assert reponse.status_code == 200, reponse.text
    return {"Authorization": f"Bearer {reponse.json()['jeton']}"}


def porteur(utilisateur_id: int, role: Role = Role.AVOCAT, minutes: int | None = None) -> dict[str, str]:
    jeton, _ = creer_jeton(utilisateur_id, role, duree_minutes=minutes)
    return {"Authorization": f"Bearer {jeton}"}


# --------------------------------------------------------------------- empreintes


def test_deux_empreintes_du_meme_mot_de_passe_diffèrent() -> None:
    """Le sel est tiré à chaque fois : deux comptes au même mot de passe ne se voient pas."""
    assert hacher("secret") != hacher("secret")


def test_une_empreinte_reconnait_son_mot_de_passe() -> None:
    empreinte = hacher("sous-huitaine")
    assert verifier("sous-huitaine", empreinte)
    assert not verifier("sous-huitaines", empreinte)


def test_un_compte_importe_ne_peut_pas_se_connecter() -> None:
    """Les comptes repris du vieux logiciel portent « ! » : aucun mot de passe ne le produit."""
    assert not verifier("", "!")
    assert not verifier("n'importe quoi", "!")
    assert not verifier("x", "empreinte abîmée")
    assert not verifier("x", "scrypt$pas$des$nombres$aa$bb")


# --------------------------------------------------------------------- connexion


def test_la_connexion_rend_un_jeton_et_le_compte(api: httpx.Client, comptes: Cabinet) -> None:
    reponse = api.post(
        "/connexion", json={"email": "m.dieng@test", "mot_de_passe": MOTS_DE_PASSE["m.dieng@test"]}
    )
    corps = reponse.json()
    assert reponse.status_code == 200
    assert corps["utilisateur"]["nom_complet"] == "Me Dieng"
    assert corps["utilisateur"]["role"] == "avocat"
    assert corps["expire_dans"] > 0
    assert "mot_de_passe" not in reponse.text


def test_un_mauvais_mot_de_passe_ne_dit_pas_si_le_compte_existe(api: httpx.Client, comptes: Cabinet) -> None:
    inconnu = api.post("/connexion", json={"email": "personne@test", "mot_de_passe": "x"})
    faux = api.post("/connexion", json={"email": "m.dieng@test", "mot_de_passe": "x"})
    assert inconnu.status_code == faux.status_code == 401
    assert inconnu.json()["detail"] == faux.json()["detail"]


def test_un_compte_desactive_ne_se_connecte_plus(api: httpx.Client, comptes: Cabinet) -> None:
    with Session(get_engine()) as session, session.begin():
        utilisateur = session.scalars(select(Utilisateur).where(Utilisateur.email == "c.sy@test")).one()
        utilisateur.actif = False
    reponse = api.post("/connexion", json={"email": "c.sy@test", "mot_de_passe": MOTS_DE_PASSE["c.sy@test"]})
    assert reponse.status_code == 401


def test_la_sante_est_ouverte(api: httpx.Client) -> None:
    reponse = api.get("/sante")
    assert reponse.status_code == 200
    assert reponse.json()["base"] is True


# --------------------------------------------------------------------- jetons


@pytest.mark.parametrize("chemin", ["/moi", "/dossiers", "/propositions"])
def test_sans_jeton_rien_nest_accessible(api: httpx.Client, chemin: str) -> None:
    assert api.get(chemin).status_code == 401


def test_un_jeton_trafique_est_refuse(api: httpx.Client, comptes: Cabinet) -> None:
    entete = connecter(api, "m.dieng@test")
    abime = {"Authorization": entete["Authorization"][:-4] + "aaaa"}
    assert api.get("/moi", headers=abime).status_code == 401


def test_un_jeton_expire_est_refuse(api: httpx.Client, comptes: Cabinet) -> None:
    assert api.get("/moi", headers=porteur(comptes.dieng, minutes=-1)).status_code == 401


def test_le_jeton_dit_qui_parle(api: httpx.Client, comptes: Cabinet) -> None:
    reponse = api.get("/moi", headers=connecter(api, "a.fall@test"))
    assert reponse.json()["email"] == "a.fall@test"


# --------------------------------------------------------------------- dossiers


def test_chaque_avocat_ne_voit_que_ses_dossiers(api: httpx.Client, comptes: Cabinet) -> None:
    dieng = {d["reference"] for d in api.get("/dossiers", headers=connecter(api, "m.dieng@test")).json()}
    fall = {d["reference"] for d in api.get("/dossiers", headers=connecter(api, "a.fall@test")).json()}
    assert dieng == {"D2026-0024", "D2026-0025"}
    assert fall == {"D2026-0027"}


def test_un_dossier_dautrui_repond_introuvable(api: httpx.Client, comptes: Cabinet) -> None:
    """404 et non 403 : un dossier fermé ne doit pas même révéler son existence."""
    entete = connecter(api, "m.dieng@test")
    for chemin in (
        "/dossiers/D2026-0027",
        "/dossiers/D2026-0027/chronologie",
        "/dossiers/D2026-0027/documents",
        "/dossiers/D2026-0027/echanges",
        "/dossiers/D2026-0027/attention",
    ):
        assert api.get(chemin, headers=entete).status_code == 404, chemin
    assert api.post("/dossiers/D2026-0027/assistant", headers=entete, json={}).status_code == 404


def test_la_fiche_dun_dossier_porte_ses_parties(api: httpx.Client, comptes: Cabinet) -> None:
    corps = api.get("/dossiers/D2026-0024", headers=connecter(api, "m.dieng@test")).json()
    assert corps["reference"] == "D2026-0024"
    assert "parties" in corps
    assert corps["nombre_documents"] >= 0


def test_la_chronologie_est_rendue_sans_appel_au_modele(api: httpx.Client, comptes: Cabinet) -> None:
    with Session(get_engine()) as session, session.begin():
        dossier = session.scalars(select(Dossier).where(Dossier.reference == "D2026-0024")).one()
        session.add(
            Document(
                dossier_id=dossier.id,
                titre="Mise en demeure",
                sens=SensEchange.SORTANT,
                chemin_fichier="D2026-0024/md.pdf",
                format="pdf",
                date_document=date(2026, 8, 13),
            )
        )
    reponse = api.get("/dossiers/D2026-0024/chronologie", headers=connecter(api, "m.dieng@test"))
    assert reponse.status_code == 200
    assert reponse.json()[0]["libelle"] == "Mise en demeure"


def test_la_fiche_dun_dossier_nomme_lequipe_qui_y_a_acces(api: httpx.Client, comptes: Cabinet) -> None:
    """L'ecran du dossier affiche cette liste : c'est la regle RLS rendue lisible."""
    corps = api.get("/dossiers/D2026-0024", headers=connecter(api, "m.dieng@test")).json()
    equipe = {membre["nom"]: membre for membre in corps["equipe"]}
    assert set(equipe) == {"Me Dieng", "Coumba Sy"}
    assert equipe["Me Dieng"]["responsable"] is True
    assert equipe["Coumba Sy"]["responsable"] is False
    # L'ecran a besoin des identifiants pour rebondir vers le client.
    assert corps["id"] > 0
    assert corps["client_id"] > 0


def test_les_echanges_rendus_sont_ceux_de_ce_dossier(api: httpx.Client, comptes: Cabinet) -> None:
    """`derniers_echanges` suit un client ; cette route ne sort pas du dossier demande."""
    with Session(get_engine()) as session, session.begin():
        dossiers = {
            dossier.reference: dossier
            for dossier in session.scalars(
                select(Dossier).where(Dossier.reference.in_(["D2026-0024", "D2026-0025"]))
            )
        }
        for reference, objet in (("D2026-0024", "Loyers impayes"), ("D2026-0025", "Autre affaire")):
            session.add(
                Communication(
                    dossier_id=dossiers[reference].id,
                    canal=Canal.EMAIL,
                    sens=SensEchange.ENTRANT,
                    date_echange=datetime(2026, 9, 1, 9, 0, tzinfo=UTC),
                    expediteur="client@test",
                    destinataires=["m.dieng@test"],
                    objet=objet,
                    corps="Maitre, " + "le bail est resilie. " * 20,
                )
            )

    corps = api.get("/dossiers/D2026-0024/echanges", headers=connecter(api, "m.dieng@test")).json()
    assert [echange["objet"] for echange in corps] == ["Loyers impayes"]
    assert corps[0]["sens"] == "reçu"
    # Un extrait, pas le corps entier, et coupe entre deux mots.
    assert len(corps[0]["extrait"]) <= 181
    assert corps[0]["extrait"].endswith("…")


def test_lecheancier_ne_montre_que_les_delais_de_ses_propres_dossiers(
    api: httpx.Client, comptes: Cabinet
) -> None:
    """Le delai de Me Fall ne doit pas apparaitre chez Me Dieng : c'est le RLS qui tranche."""
    # Le code des delais lit l horloge UTC : le test doit lire la meme.
    signe = datetime.now(UTC).date()
    with Session(get_engine()) as session, session.begin():
        for reference in ("D2026-0024", "D2026-0027"):
            dossier = session.scalars(select(Dossier).where(Dossier.reference == reference)).one()
            acte = Document(
                dossier_id=dossier.id,
                titre=f"Mise en demeure {reference}",
                sens=SensEchange.SORTANT,
                chemin_fichier=f"{reference}/md.pdf",
                format="pdf",
                date_document=signe,
            )
            session.add(acte)
            session.flush()
            session.add(
                Extraction(
                    document_id=acte.id,
                    schema="MiseEnDemeure",
                    donnees={"delai_jours": 20},
                    statut=StatutExtraction.PROPOSEE,
                )
            )

    corps = api.get(
        "/dossiers/echeances", params={"jours": 30}, headers=connecter(api, "m.dieng@test")
    ).json()
    assert [point["dossier"] for point in corps] == ["D2026-0024"]
    assert corps[0]["gravite"] == "haute"
    assert corps[0]["libelle"] == "Délai de la mise en demeure de 20 jours"

    # Une fenetre plus courte que le delai ne retient rien : la fenetre est bien appliquee.
    courte = api.get(
        "/dossiers/echeances", params={"jours": 7}, headers=connecter(api, "m.dieng@test")
    ).json()
    assert courte == []

    # Et le meme delai existe bien chez Me Fall : l'absence plus haut vient des droits.
    chez_fall = api.get("/dossiers/echeances", headers=connecter(api, "a.fall@test")).json()
    assert [point["dossier"] for point in chez_fall] == ["D2026-0027"]


def test_echeances_nest_pas_pris_pour_une_reference_de_dossier(api: httpx.Client, comptes: Cabinet) -> None:
    """FastAPI resout les routes dans l'ordre : `/echeances` doit passer avant `/{reference}`."""
    reponse = api.get("/dossiers/echeances", headers=connecter(api, "m.dieng@test"))
    assert reponse.status_code == 200
    assert isinstance(reponse.json(), list)


def test_les_points_dattention_dun_dossier_laissent_le_commercial_de_cote(
    api: httpx.Client, comptes: Cabinet
) -> None:
    """Une opportunite en sommeil parle du client, pas de l'affaire : elle n'a rien a faire ici."""
    corps = api.get("/dossiers/D2026-0024/attention", headers=connecter(api, "m.dieng@test")).json()
    libelles = " ".join(point["libelle"] for point in corps).lower()
    assert "opportunit" not in libelles
    assert "relance" not in libelles


# --------------------------------------------------------------------- recherche


def test_la_recherche_ne_sort_pas_des_dossiers_visibles(api: httpx.Client, comptes: Cabinet) -> None:
    """L'extrait du jugement appartient au dossier de Me Fall : Me Dieng ne doit rien voir."""
    corps = {"texte": "Le tribunal condamne", "limite": 5}
    pour_fall = api.post("/recherche", headers=connecter(api, "a.fall@test"), json=corps)
    pour_dieng = api.post("/recherche", headers=connecter(api, "m.dieng@test"), json=corps)
    assert pour_fall.status_code == pour_dieng.status_code == 200
    assert len(pour_fall.json()) == 1
    assert pour_dieng.json() == []


def test_la_recherche_dit_par_quelle_voie_elle_a_trouve(api: httpx.Client, comptes: Cabinet) -> None:
    resultats = api.post(
        "/recherche", headers=connecter(api, "a.fall@test"), json={"texte": "tribunal condamne"}
    ).json()
    assert resultats
    assert resultats[0]["trouve_par"]


# --------------------------------------------------------------------- clients et documents


def _client_de_dieng(api: httpx.Client) -> int:
    reponse = api.get("/clients/recherche", headers=connecter(api, "m.dieng@test"), params={"nom": "Sine"})
    assert reponse.status_code == 200, reponse.text
    return int(reponse.json()["client_id"])


def test_un_client_dautrui_repond_introuvable(api: httpx.Client, comptes: Cabinet) -> None:
    client_id = _client_de_dieng(api)
    assert api.get(f"/clients/{client_id}", headers=connecter(api, "a.fall@test")).status_code == 404


def test_la_fiche_client_ne_compte_que_les_dossiers_visibles(api: httpx.Client, comptes: Cabinet) -> None:
    client_id = _client_de_dieng(api)
    vu_par_dieng = api.get(f"/clients/{client_id}", headers=connecter(api, "m.dieng@test")).json()
    vu_par_sy = api.get(f"/clients/{client_id}", headers=connecter(api, "c.sy@test")).json()
    assert vu_par_dieng["dossiers_visibles"] == 2
    assert vu_par_sy["dossiers_visibles"] == 1


def test_les_points_dattention_sont_rendus_sans_modele(api: httpx.Client, comptes: Cabinet) -> None:
    client_id = _client_de_dieng(api)
    reponse = api.get(f"/clients/{client_id}/attention", headers=connecter(api, "m.dieng@test"))
    assert reponse.status_code == 200
    assert isinstance(reponse.json(), list)


def test_une_piece_dautrui_repond_introuvable(api: httpx.Client, comptes: Cabinet) -> None:
    with Session(get_engine()) as session:
        document = session.scalars(select(Document)).first()
        assert document is not None  # le jugement du dossier de Me Fall
        identifiant = document.id
    entete = connecter(api, "m.dieng@test")
    assert api.get(f"/documents/{identifiant}", headers=entete).status_code == 404
    assert api.get(f"/documents/{identifiant}/texte", headers=entete).status_code == 404
    assert api.post(f"/documents/{identifiant}/analyse", headers=entete, json={}).status_code == 404


def test_une_piece_sans_extraction_le_dit(api: httpx.Client, comptes: Cabinet) -> None:
    with Session(get_engine()) as session:
        document = session.scalars(select(Document)).first()
        assert document is not None
        identifiant = document.id
    reponse = api.get(f"/documents/{identifiant}/extraction", headers=connecter(api, "a.fall@test"))
    assert reponse.status_code == 404
    assert "jurismind.extraction" in reponse.json()["detail"]


def test_une_extraction_remonte_ses_champs_douteux(api: httpx.Client, comptes: Cabinet) -> None:
    with Session(get_engine()) as session, session.begin():
        document = session.scalars(select(Document)).one()
        session.add(
            Extraction(
                document_id=document.id,
                schema="Jugement",
                donnees={"montant_alloue_fcfa": 13_750_000, "vide": None},
                champs_douteux=["montant_alloue_fcfa"],
                statut=StatutExtraction.PROPOSEE,
            )
        )
        identifiant = document.id
    corps = api.get(f"/documents/{identifiant}/extraction", headers=connecter(api, "a.fall@test")).json()
    assert corps["champs_douteux"] == ["montant_alloue_fcfa"]
    assert corps["relue"] is False
    assert "vide" not in corps["donnees"]


# --------------------------------------------------------------------- courrier et décisions


def _proposition(
    dossier_reference: str | None, type_proposition: TypeProposition = TypeProposition.RATTACHEMENT
) -> int:
    with Session(get_engine()) as session, session.begin():
        echange = session.scalars(select(Communication).where(Communication.dossier_id.is_(None))).first()
        if echange is None:
            echange = Communication(
                dossier_id=None,
                canal=Canal.EMAIL,
                sens=SensEchange.ENTRANT,
                date_echange=datetime(2026, 9, 20, 10, tzinfo=UTC),
                expediteur="prospect@test",
                corps="Demande de rendez-vous",
            )
            session.add(echange)
            session.flush()
        dossier_id = None
        if dossier_reference is not None:
            dossier_id = session.scalars(
                select(Dossier.id).where(Dossier.reference == dossier_reference)
            ).one()
        proposition = Proposition(
            type=type_proposition,
            communication_id=echange.id,
            dossier_id=dossier_id,
            titre="Rattacher l'email",
            justification="l'expéditeur est une partie du dossier",
            confiance=Confiance.HAUTE,
            donnees={},
        )
        session.add(proposition)
        session.flush()
        return int(proposition.id)


def test_la_file_des_propositions_porte_leur_fondement(api: httpx.Client, comptes: Cabinet) -> None:
    _proposition("D2026-0024")
    corps = api.get("/propositions", headers=connecter(api, "m.dieng@test")).json()
    assert len(corps) == 1
    assert corps[0]["justification"]
    assert corps[0]["statut"] == "proposee"


def test_une_proposition_qui_vise_le_dossier_dautrui_est_invisible(
    api: httpx.Client, comptes: Cabinet
) -> None:
    identifiant = _proposition("D2026-0024")
    entete = connecter(api, "a.fall@test")
    assert api.get("/propositions", headers=entete).json() == []
    assert api.post(f"/propositions/{identifiant}/validation", headers=entete).status_code == 404


def test_valider_produit_leffet_et_garde_qui_la_autorise(api: httpx.Client, comptes: Cabinet) -> None:
    identifiant = _proposition("D2026-0024")
    corps = api.post(f"/propositions/{identifiant}/validation", headers=connecter(api, "m.dieng@test")).json()
    assert corps["statut"] == "appliquee"
    assert corps["decide_par_id"] == comptes.dieng
    assert corps["decide_le"] is not None

    with Session(get_engine()) as session:
        echange = session.scalars(
            select(Communication).where(Communication.expediteur == "prospect@test")
        ).one()
        dossier_id = session.scalars(select(Dossier.id).where(Dossier.reference == "D2026-0024")).one()
    assert echange.dossier_id == dossier_id


def test_on_ne_valide_pas_deux_fois(api: httpx.Client, comptes: Cabinet) -> None:
    identifiant = _proposition("D2026-0024")
    entete = connecter(api, "m.dieng@test")
    assert api.post(f"/propositions/{identifiant}/validation", headers=entete).status_code == 200
    seconde = api.post(f"/propositions/{identifiant}/validation", headers=entete)
    assert seconde.status_code == 409


def test_le_rejet_garde_son_motif(api: httpx.Client, comptes: Cabinet) -> None:
    identifiant = _proposition("D2026-0024", TypeProposition.BROUILLON)
    corps = api.post(
        f"/propositions/{identifiant}/rejet",
        headers=connecter(api, "m.dieng@test"),
        json={"motif": "ton trop engageant"},
    ).json()
    assert corps["statut"] == StatutProposition.REJETEE
    assert corps["donnees"]["motif_du_rejet"] == "ton trop engageant"


def test_une_proposition_inconnue_repond_introuvable(api: httpx.Client, comptes: Cabinet) -> None:
    entete = connecter(api, "m.dieng@test")
    assert api.post("/propositions/999999/validation", headers=entete).status_code == 404
    assert api.post("/propositions/999999/rejet", headers=entete, json={}).status_code == 404


def test_un_administrateur_ne_tranche_pas(api: httpx.Client, comptes: Cabinet) -> None:
    """Il administre les comptes ; il n'a aucun dossier et ne décide pas pour les avocats."""
    identifiant = _proposition(None, TypeProposition.TACHE_CRM)
    entete = connecter(api, "admin@test")
    assert api.post(f"/propositions/{identifiant}/validation", headers=entete).status_code == 403
    assert api.post("/courrier/tri", headers=entete, json={"limite": 1}).status_code == 403


def test_le_courrier_a_trier_est_visible_du_cabinet(api: httpx.Client, comptes: Cabinet) -> None:
    pour_avocat = api.get("/courrier/a-trier", headers=connecter(api, "m.dieng@test"))
    pour_admin = api.get("/courrier/a-trier", headers=connecter(api, "admin@test"))
    assert len(pour_avocat.json()) == 1
    assert pour_admin.json() == []


# --------------------------------------------------------------------- conflits (bonus)


def _partie_adverse(reference: str, nom: str) -> None:
    with Session(get_engine()) as session, session.begin():
        dossier = session.scalars(select(Dossier).where(Dossier.reference == reference)).one()
        session.add(Partie(dossier_id=dossier.id, qualite=QualitePartie.ADVERSE, nom=nom))


def test_la_verification_dune_identite_classe_ce_quelle_trouve(api: httpx.Client, comptes: Cabinet) -> None:
    corps = api.post(
        "/conformite/verification",
        headers=connecter(api, "m.dieng@test"),
        json={"nom": "Dakar Télécom SA"},
    ).json()
    assert len(corps) == 1
    assert corps[0]["niveau"] == "a_verifier"
    assert corps[0]["client"] == "Dakar Télécom SARL"


def test_le_controle_regarde_au_dela_des_dossiers_du_demandeur(api: httpx.Client, comptes: Cabinet) -> None:
    """Me Dieng n'a pas accès à D2026-0027, mais il doit être averti du conflit."""
    corps = api.post(
        "/conformite/verification",
        headers=connecter(api, "m.dieng@test"),
        json={"nom": "Dakar Télécom SARL"},
    ).json()
    assert corps
    assert corps[0]["dossiers_visibles"] == []  # mais il n'apprend pas lesquels
    assert corps[0]["autres_dossiers"] == 1


def test_celui_qui_a_acces_voit_la_reference(api: httpx.Client, comptes: Cabinet) -> None:
    corps = api.post(
        "/conformite/verification",
        headers=connecter(api, "a.fall@test"),
        json={"nom": "Dakar Télécom SARL"},
    ).json()
    assert corps[0]["dossiers_visibles"] == ["D2026-0027"]


def test_les_conflits_dun_dossier_sont_verifiables(api: httpx.Client, comptes: Cabinet) -> None:
    _partie_adverse("D2026-0024", "Dakar Télécom SA")
    corps = api.get("/conformite/dossiers/D2026-0024", headers=connecter(api, "m.dieng@test")).json()
    assert [c["client"] for c in corps] == ["Dakar Télécom SARL"]


def test_un_dossier_inconnu_repond_introuvable(api: httpx.Client, comptes: Cabinet) -> None:
    reponse = api.get("/conformite/dossiers/D1999-0001", headers=connecter(api, "m.dieng@test"))
    assert reponse.status_code == 404


def test_le_balayage_nomme_le_dossier_en_cause(api: httpx.Client, comptes: Cabinet) -> None:
    _partie_adverse("D2026-0025", "Dakar Télécom SA")
    corps = api.get("/conformite/balayage", headers=connecter(api, "m.dieng@test")).json()
    assert [(r["dossier"], r["conflit"]["client"]) for r in corps] == [("D2026-0025", "Dakar Télécom SARL")]


def test_un_administrateur_ne_controle_pas_les_conflits(api: httpx.Client, comptes: Cabinet) -> None:
    """C'est un acte professionnel d'avocat, pas une tâche d'administration."""
    entete = connecter(api, "admin@test")
    assert api.post("/conformite/verification", headers=entete, json={"nom": "X"}).status_code == 403
    assert api.get("/conformite/balayage", headers=entete).status_code == 403


def test_un_avocat_valide_une_extraction(api: httpx.Client, comptes: Cabinet) -> None:
    """Une extraction est une proposition ; cette route est l'endroit où un humain tranche."""
    with Session(get_engine()) as session, session.begin():
        document = session.scalars(select(Document)).one()
        session.add(
            Extraction(
                document_id=document.id,
                schema="Jugement",
                donnees={"montant_alloue_fcfa": 0},
                champs_douteux=["montant_alloue_fcfa"],
                statut=StatutExtraction.PROPOSEE,
            )
        )
        identifiant = document.id

    corps = api.post(
        f"/documents/{identifiant}/extraction/validation",
        headers=connecter(api, "a.fall@test"),
        json={"corrections": {"montant_alloue_fcfa": 13750000}},
    ).json()
    assert corps["relue"] is True
    assert corps["donnees"]["montant_alloue_fcfa"] == 13750000
    # Un champ corrigé cesse d'être douteux : c'est l'avocat qui a tranché.
    assert corps["champs_douteux"] == []

    with Session(get_engine()) as session:
        extraction = session.scalars(select(Extraction)).one()
    assert extraction.statut is StatutExtraction.VALIDEE
    assert extraction.valide_par_id == comptes.fall
    assert extraction.valide_le is not None


def test_valider_sans_extraction_le_dit(api: httpx.Client, comptes: Cabinet) -> None:
    with Session(get_engine()) as session:
        document = session.scalars(select(Document)).one()
        identifiant = document.id
    reponse = api.post(
        f"/documents/{identifiant}/extraction/validation",
        headers=connecter(api, "a.fall@test"),
        json={},
    )
    assert reponse.status_code == 404


def test_on_ne_valide_pas_lextraction_dune_piece_dautrui(api: httpx.Client, comptes: Cabinet) -> None:
    with Session(get_engine()) as session:
        document = session.scalars(select(Document)).one()
        identifiant = document.id
    reponse = api.post(
        f"/documents/{identifiant}/extraction/validation",
        headers=connecter(api, "m.dieng@test"),
        json={},
    )
    assert reponse.status_code == 404


# --------------------------------------------------------------------- interface web


def test_la_racine_mene_a_linterface(api: httpx.Client) -> None:
    reponse = api.get("/", follow_redirects=False)
    assert reponse.status_code in (301, 302, 307, 308)
    assert reponse.headers["location"] == "/app/"


def test_linterface_est_servie_par_lapi(api: httpx.Client) -> None:
    """Une seule origine : le jeton ne traverse jamais un autre domaine, donc pas de CORS."""
    page = api.get("/app/")
    assert page.status_code == 200
    assert "JurisMind" in page.text
    assert api.get("/app/styles.css").status_code == 200
    assert api.get("/app/app.js").status_code == 200
    assert api.get("/app/dossier.js").status_code == 200


def test_linterface_ne_laisse_filtrer_aucun_secret(api: httpx.Client) -> None:
    """Les fichiers servis sont publics : ni mot de passe, ni clé, ni chaîne de connexion."""
    interdits = ("postgresql://", "api_secret", "jurismind_app", "crm-dev-key")
    for fichier in ("/app/index.html", "/app/app.js", "/app/dossier.js", "/app/styles.css"):
        contenu = api.get(fichier).text.lower()
        for secret in interdits:
            assert secret not in contenu, f"{secret} exposé dans {fichier}"


# --------------------------------------------------------------------- documentation


def test_la_documentation_openapi_decrit_toutes_les_fonctionnalites(api: httpx.Client) -> None:
    """C'est elle que le cabinet lira : elle doit couvrir F2 à F9."""
    schema: dict[str, Any] = api.get("/openapi.json").json()
    chemins = set(schema["paths"])
    for attendu in (
        "/connexion",
        "/recherche",
        "/questions",
        "/dossiers/{reference}/assistant",
        "/clients/{client_id}/assistant",
        "/documents/{document_id}/analyse",
        "/courrier/tri",
        "/propositions/{proposition_id}/validation",
        "/conformite/verification",
    ):
        assert attendu in chemins, attendu
    # Chaque route porte un résumé lisible, pas seulement un nom de fonction.
    for chemin, methodes in schema["paths"].items():
        for methode, details in methodes.items():
            assert details.get("summary"), f"{methode} {chemin} sans résumé"
