"""Recherche sémantique (F3) et réponses citées (F2, F11).

Les deux routes reçoivent la session ouverte au nom de l'utilisateur : le filtrage par droits
est fait par PostgreSQL **avant** la recherche, pas après par un tri des résultats.
"""

from dataclasses import asdict

from fastapi import APIRouter

from jurismind.api.schemas import (
    Citation,
    Controle,
    DemandeQuestion,
    DemandeRecherche,
    Filtre,
    ReponseCitee,
    ResultatRecherche,
)
from jurismind.api.securite import SessionRequise
from jurismind.rag import repondre
from jurismind.rag.reponse import CONTROLES
from jurismind.retrieval import Filtres, rechercher

routeur = APIRouter(tags=["Recherche"])


def filtres_de(filtre: Filtre) -> Filtres:
    return Filtres(
        dossier_id=filtre.dossier_id,
        client_id=filtre.client_id,
        categories=list(filtre.categories),
        depuis=filtre.depuis,
        jusqu_a=filtre.jusqu_a,
    )


@routeur.post(
    "/recherche",
    response_model=list[ResultatRecherche],
    summary="Recherche hybride dans les pièces et les échanges",
)
def recherche(demande: DemandeRecherche, session: SessionRequise) -> list[ResultatRecherche]:
    """Fusionne trois voies : proximité de sens, plein texte français, et référence exacte.

    `trouve_par` dit laquelle a remonté chaque extrait — utile pour comprendre un résultat
    surprenant.
    """
    resultats = rechercher(session, demande.texte, filtres=filtres_de(demande.filtres), limite=demande.limite)
    return [
        ResultatRecherche(
            extrait_id=resultat.extrait.id,
            reference=resultat.reference,
            contenu=resultat.extrait.contenu,
            score=resultat.score,
            similarite=resultat.similarite,
            trouve_par=resultat.trouve_par,
            dossier_id=resultat.extrait.dossier_id,
        )
        for resultat in resultats
    ]


@routeur.post(
    "/questions",
    response_model=ReponseCitee,
    summary="Poser une question sur les pièces du cabinet",
)
def question(demande: DemandeQuestion, session: SessionRequise) -> ReponseCitee:
    """Répond **uniquement** à partir des pièces, avec ses sources, ou s'abstient.

    Quatre vérifications précèdent l'affichage (sources valides, aveu d'ignorance, référence
    croisée, citation littérale ou ancrage des chiffres). Quand elles échouent, `abstention`
    vaut vrai et le texte dit que la réponse n'a pas été trouvée : c'est un résultat, pas une
    erreur. Compter 15 à 30 s par question sur une machine sans GPU.
    """
    reponse = repondre(session, demande.question, filtres=filtres_de(demande.filtres))
    return ReponseCitee(
        texte=reponse.texte,
        citations=[Citation(**asdict(citation)) for citation in reponse.citations],
        abstention=reponse.abstention,
        secondes=reponse.secondes,
        sources_examinees=reponse.sources_examinees,
        controles=[
            Controle(nom=nom, libelle=CONTROLES[nom], reussi=reussi)
            for nom, reussi in reponse.controles.items()
        ],
    )
