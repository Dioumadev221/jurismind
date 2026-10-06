"""Démonstration de JurisMind (F10).

    uv run uvicorn jurismind.api.main:app --port 8000     # dans un terminal
    uv run streamlit run src/jurismind/demo/app.py        # dans un autre

Six écrans, un par usage de l'offre. Tout passe par l'API avec le jeton de l'utilisateur
connecté : ce qui est affiché est exactement ce que cet avocat a le droit de voir.

Trois choses que cette démo doit rendre visibles, parce qu'elles sont le cœur du projet :

- une réponse **cite ses sources**, ou bien elle s'abstient — et l'abstention est affichée
  comme un résultat, pas comme une panne ;
- un point d'attention et une proposition **disent sur quoi ils se fondent** ;
- rien ne se produit sans un clic humain sur « Valider ».
"""

from typing import Any

import streamlit as st

from jurismind.demo.client import Api, ApiIndisponible, ApiRefuse

API_PAR_DEFAUT = "http://localhost:8000"
ECRANS = (
    "Mes dossiers",
    "Un client",
    "Une question",
    "Une pièce",
    "Le courrier",
    "Conflits d'intérêts",
)
GRAVITES = {"haute": "🔴", "moyenne": "🟠"}
PRIORITES = {"haute": "🔴", "moyenne": "🟠", "basse": "⚪"}
LENT = "Un modèle local tourne sur le processeur : compter 20 à 100 secondes."


def api() -> Api:
    return Api(st.session_state.get("api_url", API_PAR_DEFAUT), st.session_state.get("jeton"))


def montrer_erreur(erreur: Exception) -> None:
    if isinstance(erreur, ApiIndisponible):
        st.error(f"{erreur}. Démarrer l'API : `uv run uvicorn jurismind.api.main:app --port 8000`")
    elif isinstance(erreur, ApiRefuse):
        st.warning(f"{erreur.detail} (code {erreur.code})")
    else:  # pragma: no cover - filet de sécurité
        st.error(str(erreur))


# --------------------------------------------------------------------------- connexion


def ecran_connexion() -> None:
    st.title("JurisMind")
    st.caption("Recherche, réponses citées et agents pour un cabinet d'avocats")
    st.info(
        "Les mots de passe de démonstration sont dans `data/comptes-demo.txt`, créé par "
        "`uv run python -m jurismind.api.comptes --demo`."
    )
    with st.form("connexion"):
        url = st.text_input("API", value=st.session_state.get("api_url", API_PAR_DEFAUT))
        email = st.text_input("Adresse", placeholder="m.dieng@teranga-avocats.example")
        mot_de_passe = st.text_input("Mot de passe", type="password")
        if st.form_submit_button("Se connecter", type="primary"):
            st.session_state["api_url"] = url
            try:
                reponse = Api(url).connexion(email, mot_de_passe)
            except (ApiIndisponible, ApiRefuse) as erreur:
                montrer_erreur(erreur)
                return
            st.session_state["jeton"] = reponse["jeton"]
            st.session_state["utilisateur"] = reponse["utilisateur"]
            st.rerun()


# --------------------------------------------------------------------------- dossiers


def ecran_dossiers() -> None:
    st.header("Mes dossiers")
    st.caption("Cette liste est produite par PostgreSQL : elle ne contient que vos dossiers.")
    dossiers = api().get("/dossiers")
    if not dossiers:
        st.info("Aucun dossier ouvert à ce compte.")
        return

    st.metric("Dossiers visibles", len(dossiers))
    etiquettes = {f"{d['reference']} — {d['intitule']}": d for d in dossiers}
    choisi = etiquettes[st.selectbox("Dossier", list(etiquettes))]
    reference = choisi["reference"]

    colonnes = st.columns(4)
    colonnes[0].metric("Statut", choisi["statut"])
    colonnes[1].metric("Matière", choisi["matiere"])
    colonnes[2].metric(
        "Enjeu (FCFA)", f"{choisi['enjeu_fcfa']:,}".replace(",", " ") if choisi["enjeu_fcfa"] else "—"
    )
    colonnes[3].metric("Responsable", choisi["responsable"] or "—")

    onglets = st.tabs(["Chronologie", "Pièces", "Conflits", "Assistant"])
    with onglets[0]:
        st.caption("Construite par le code à partir des dates en base : aucun modèle n'intervient.")
        evenements = api().get(f"/dossiers/{reference}/chronologie")
        for evenement in evenements:
            detail = f" — {evenement['detail']}" if evenement["detail"] else ""
            st.write(f"**{evenement['date']}** · {evenement['libelle']}{detail}")
        if not evenements:
            st.info("Aucun événement daté dans ce dossier.")
    with onglets[1]:
        for piece in api().get(f"/dossiers/{reference}/documents"):
            reconnu = piece["categorie_detectee"]
            saisi = piece["categorie_source"] or "—"
            marque = " · ⚠ saisi " + saisi if reconnu and reconnu != saisi else ""
            st.write(f"`{piece['id']}` **{piece['titre']}** — {reconnu or saisi}{marque}")
    with onglets[2]:
        afficher_conflits(
            api().get(f"/conformite/dossiers/{reference}"),
            "Aucune partie adverse de ce dossier ne porte le nom d'un client du cabinet.",
        )
    with onglets[3]:
        demande = st.text_input("Demande", value="résume ce dossier", key=f"agent_dossier_{reference}")
        st.caption(LENT + " Une chronologie, elle, revient instantanément.")
        if st.button("Demander", key=f"bouton_dossier_{reference}"):
            with st.spinner("L'agent travaille…"):
                reponse = api().post(f"/dossiers/{reference}/assistant", {"demande": demande})
            afficher_reponse_agent(reponse)


def afficher_reponse_agent(reponse: dict[str, Any]) -> None:
    st.caption(f"intention retenue : **{reponse['intention']}** · {reponse['secondes']:.0f} s")
    if reponse["abstention"]:
        st.warning(reponse["texte"])
        st.caption("L'abstention est un résultat : les pièces ne permettaient pas de conclure.")
        return
    st.markdown(reponse["texte"].replace("\n", "  \n"))
    if reponse["citations"]:
        with st.expander(f"{len(reponse['citations'])} source(s) citée(s)"):
            for citation in reponse["citations"]:
                st.write(f"[{citation['numero']}] {citation['reference']}")


# --------------------------------------------------------------------------- clients


def ecran_client() -> None:
    st.header("Un client")
    nom = st.text_input("Nom du client", value="Sine Services SA")
    if not nom:
        return
    try:
        trouve = api().get("/clients/recherche", nom=nom)
    except ApiRefuse as erreur:
        montrer_erreur(erreur)
        return
    client_id = trouve["client_id"]

    colonnes = st.columns(3)
    colonnes[0].metric("Dossiers visibles", trouve["dossiers_visibles"])
    colonnes[1].metric("En cours", trouve["dossiers_en_cours"])
    enjeu = trouve["enjeu_total_fcfa"]
    colonnes[2].metric("Enjeu cumulé (FCFA)", f"{enjeu:,}".replace(",", " ") if enjeu else "—")
    st.caption("« Visibles » : la fiche ne compte que les dossiers ouverts à votre compte.")

    onglets = st.tabs(["Points d'attention", "Dossiers", "Derniers échanges", "Synthèse"])
    with onglets[0]:
        st.caption(
            "Déduits des données par des règles, jamais demandés à un modèle. Chacun remonte "
            "à la date, au montant ou au statut qui l'a déclenché."
        )
        points = api().get(f"/clients/{client_id}/attention")
        for point in points:
            marque = GRAVITES.get(point["gravite"], "•")
            ou = f" · `{point['dossier']}`" if point["dossier"] else ""
            st.write(f"{marque} **{point['libelle']}**{ou} — {point['detail']}")
        if not points:
            st.success("Rien à signaler. Une liste vide est une information.")
    with onglets[1]:
        for dossier in api().get(f"/clients/{client_id}/dossiers"):
            st.write(f"`{dossier['reference']}` {dossier['intitule']} — {dossier['statut']}")
    with onglets[2]:
        for echange in api().get(f"/clients/{client_id}/echanges"):
            st.write(
                f"**{echange['date']}** · `{echange['dossier']}` {echange['sens']} "
                f"{echange['interlocuteur'] or ''} — {echange['objet'] or 'sans objet'}"
            )
    with onglets[3]:
        st.caption(LENT)
        if st.button("Faire le point", key=f"synthese_{client_id}"):
            with st.spinner("L'agent rédige…"):
                reponse = api().post(f"/clients/{client_id}/assistant", {"demande": "fais le point"})
            afficher_reponse_agent(reponse)


# --------------------------------------------------------------------------- questions


def ecran_question() -> None:
    st.header("Une question sur les pièces")
    st.caption(
        "La réponse ne vient que des pièces, avec ses sources — ou bien l'agent s'abstient. "
        "La recherche est bornée à vos dossiers par PostgreSQL, avant même d'avoir lieu."
    )
    question = st.text_input("Question", value="Quel délai le débiteur a-t-il pour former opposition ?")
    dossiers = api().get("/dossiers")
    etiquettes = {"— tous mes dossiers —": None} | {
        f"{d['reference']} — {d['intitule'][:48]}": d["id"] for d in dossiers
    }
    dossier_id = etiquettes[st.selectbox("Restreindre à", list(etiquettes))]
    filtres = {"dossier_id": dossier_id} if dossier_id else {}

    onglets = st.tabs(["Réponse citée", "Extraits trouvés"])
    with onglets[0]:
        st.caption(LENT)
        if st.button("Répondre", type="primary"):
            with st.spinner("Recherche, puis rédaction…"):
                reponse = api().post("/questions", {"question": question, "filtres": filtres})
            if reponse["abstention"]:
                st.warning(reponse["texte"])
            else:
                st.markdown(reponse["texte"])
            st.caption(f"{reponse['sources_examinees']} extrait(s) examiné(s) · {reponse['secondes']:.0f} s")
            for citation in reponse["citations"]:
                st.write(f"[{citation['numero']}] {citation['reference']}")
    with onglets[1]:
        st.caption("La recherche seule, sans modèle : immédiate.")
        if st.button("Chercher"):
            resultats = api().post("/recherche", {"texte": question, "filtres": filtres, "limite": 6})
            for resultat in resultats:
                with st.expander(f"{resultat['reference']} · trouvé par {resultat['trouve_par']}"):
                    st.write(resultat["contenu"])


# --------------------------------------------------------------------------- pièces


def ecran_piece() -> None:
    st.header("Une pièce")
    dossiers = api().get("/dossiers")
    if not dossiers:
        st.info("Aucun dossier ouvert à ce compte.")
        return
    etiquettes = {f"{d['reference']} — {d['intitule'][:48]}": d["reference"] for d in dossiers}
    reference = etiquettes[st.selectbox("Dossier", list(etiquettes))]
    pieces = api().get(f"/dossiers/{reference}/documents")
    if not pieces:
        st.info("Ce dossier n'a pas encore de pièce lue.")
        return
    titres = {f"{p['id']} · {p['titre']}": p for p in pieces}
    piece = titres[st.selectbox("Pièce", list(titres))]

    colonnes = st.columns(3)
    colonnes[0].metric("Saisi par le cabinet", piece["categorie_source"] or "—")
    colonnes[1].metric("Reconnu par JurisMind", piece["categorie_detectee"] or "—")
    colonnes[2].metric("Lu par OCR", "oui" if piece["lu_par_ocr"] else "non")

    onglets = st.tabs(["Analyse", "Valeurs extraites", "Texte lu"])
    with onglets[0]:
        st.caption(
            "Le type retenu appartient à une liste fermée ; chaque point relevé est accompagné "
            "de la phrase du document qui le porte. " + LENT
        )
        if st.button("Analyser", key=f"analyse_{piece['id']}"):
            with st.spinner("L'agent lit la pièce…"):
                reponse = api().post(f"/documents/{piece['id']}/analyse", {"demande": ""})
            afficher_reponse_agent(reponse)
    with onglets[1]:
        try:
            extraction = api().get(f"/documents/{piece['id']}/extraction")
        except ApiRefuse as erreur:
            st.info(erreur.detail)
        else:
            st.write(f"Schéma **{extraction['schema']}** · relue : {extraction['relue']}")
            st.json(extraction["donnees"])
            if extraction["champs_douteux"]:
                st.warning(
                    "À relire — ces valeurs ne se retrouvent pas telles quelles dans le "
                    f"document : {', '.join(extraction['champs_douteux'])}"
                )
    with onglets[2]:
        texte = api().get(f"/documents/{piece['id']}/texte")
        st.caption(f"{texte['caracteres']} caractères" + (" (OCR)" if texte["lu_par_ocr"] else ""))
        st.text_area("Texte", value=texte["texte"], height=320, disabled=True)


# --------------------------------------------------------------------------- courrier


def ecran_courrier() -> None:
    st.header("Le courrier")
    st.caption(
        "L'agent propose ; vous décidez. Rien ne se produit avant un clic sur « Valider », "
        "et la décision reste inscrite en base avec votre nom."
    )

    a_trier = api().get("/courrier/a-trier")
    colonnes = st.columns([3, 1])
    colonnes[0].write(f"**{len(a_trier)} échange(s)** qu'aucun dossier ne réclame.")
    if colonnes[1].button("Trier le courrier", disabled=not a_trier):
        with st.spinner("L'agent examine chaque email…"):
            reponse = api().post("/courrier/tri", {"limite": 20})
        st.code(reponse["texte"])
        st.rerun()
    for echange in a_trier:
        st.write(f"· **{echange['objet'] or 'sans objet'}** — de {echange['expediteur']}")

    st.divider()
    propositions = api().get("/propositions")
    st.subheader(f"{len(propositions)} décision(s) à prendre")
    if not propositions:
        st.success("Rien n'attend de décision.")
        return

    for proposition in propositions:
        marque = GRAVITES.get("haute" if proposition["confiance"] == "haute" else "moyenne", "•")
        with st.container(border=True):
            st.write(f"{marque} **{proposition['titre']}**")
            st.caption(f"{proposition['type']} · fondement : {proposition['justification']}")
            if proposition["contenu"]:
                st.text_area(
                    "Contenu proposé",
                    value=proposition["contenu"],
                    height=140,
                    disabled=True,
                    key=f"contenu_{proposition['id']}",
                )
            if priorite := proposition["donnees"].get("priorite"):
                st.caption(
                    f"priorité {PRIORITES.get(priorite, '')} {priorite} — "
                    f"{proposition['donnees'].get('priorite_pourquoi', '')}"
                )
            boutons = st.columns([1, 1, 4])
            if boutons[0].button("Valider", key=f"ok_{proposition['id']}", type="primary"):
                try:
                    tranchee = api().post(f"/propositions/{proposition['id']}/validation")
                except ApiRefuse as erreur:
                    montrer_erreur(erreur)
                else:
                    st.success(f"#{tranchee['id']} → {tranchee['statut']}")
                    if tranchee["erreur"]:
                        st.warning(f"Application échouée : {tranchee['erreur']}")
                    st.rerun()
            if boutons[1].button("Rejeter", key=f"non_{proposition['id']}"):
                try:
                    api().post(
                        f"/propositions/{proposition['id']}/rejet",
                        {"motif": "rejetée depuis la démonstration"},
                    )
                except ApiRefuse as erreur:
                    montrer_erreur(erreur)
                else:
                    st.rerun()


# --------------------------------------------------------------- conflits d'intérêts


def afficher_conflits(conflits: list[dict[str, Any]], message_vide: str) -> None:
    """Un conflit se lit, il ne se tranche pas : on montre ce qui a déclenché l'alerte."""
    if not conflits:
        st.success(message_vide)
        st.caption("Une liste vide dit ce qui a été cherché, pas que tout va bien.")
        return
    for conflit in conflits:
        certain = conflit["niveau"] == "certain"
        with st.container(border=True):
            marque = "🔴" if certain else "🟠"
            st.write(f"{marque} **{conflit['partie']}** ≈ **{conflit['client']}**")
            st.caption(f"{conflit['relation']} · {conflit['explication']}")
            if conflit["dossiers_visibles"]:
                st.write(
                    "Dossiers concernés que vous pouvez consulter : "
                    + ", ".join(f"`{reference}`" for reference in conflit["dossiers_visibles"])
                )
            if conflit["autres_dossiers"]:
                st.caption(
                    f"{conflit['autres_dossiers']} autre(s) dossier(s) du cabinet sont "
                    "concernés : ils ne vous sont pas nommés."
                )


def ecran_conflits() -> None:
    st.header("Conflits d'intérêts")
    st.caption(
        "Un avocat ne peut pas agir contre son propre client. Ce contrôle regarde **tout "
        "le cabinet**, y compris les dossiers qui vous sont fermés — sans cela il "
        "manquerait justement les conflits qu'il cherche. Il ne vous nomme que les "
        "dossiers auxquels vous avez accès, et chaque vérification est inscrite au journal."
    )

    onglets = st.tabs(["Avant d'accepter une affaire", "Tout le cabinet"])
    with onglets[0]:
        nom = st.text_input("Dénomination de la partie adverse", value="Sine Services SARL")
        if st.button("Vérifier", type="primary") and nom.strip():
            afficher_conflits(
                api().post("/conformite/verification", {"nom": nom}),
                f"Rien trouvé au nom de « {nom} » dans les données du cabinet.",
            )
    with onglets[1]:
        st.caption("Toutes les parties adverses du cabinet, confrontées à sa liste de clients.")
        if st.button("Lancer le balayage"):
            resultats = api().get("/conformite/balayage")
            if not resultats:
                st.success("Aucune collision dans le cabinet.")
            for resultat in resultats:
                st.write(f"Dossier `{resultat['dossier']}` :")
                afficher_conflits([resultat["conflit"]], "")


# --------------------------------------------------------------------------- assemblage


def main() -> None:
    st.set_page_config(page_title="JurisMind", page_icon="⚖️", layout="wide")
    if not st.session_state.get("jeton"):
        ecran_connexion()
        return

    utilisateur = st.session_state["utilisateur"]
    with st.sidebar:
        st.write(f"**{utilisateur['nom_complet']}**")
        st.caption(f"{utilisateur['email']} · {utilisateur['role']}")
        ecran = st.radio("Écran", ECRANS, label_visibility="collapsed")
        st.divider()
        if st.button("Se déconnecter"):
            st.session_state.clear()
            st.rerun()
        st.caption(
            "Tout ce qui s'affiche passe par l'API avec votre jeton : c'est exactement ce que "
            "vous avez le droit de voir."
        )

    ecrans = {
        "Mes dossiers": ecran_dossiers,
        "Un client": ecran_client,
        "Une question": ecran_question,
        "Une pièce": ecran_piece,
        "Le courrier": ecran_courrier,
        "Conflits d'intérêts": ecran_conflits,
    }
    try:
        ecrans[str(ecran)]()
    except (ApiIndisponible, ApiRefuse) as erreur:
        montrer_erreur(erreur)


# Streamlit exécute ce fichier sous le nom `__main__` : la garde évite que la démo
# se lance au simple import du module (par un test, ou par un outil d'inspection).
if __name__ == "__main__":
    main()
