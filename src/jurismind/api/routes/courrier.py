"""Le courrier entrant et la file des décisions à prendre (F9).

C'est ici que l'API cesse de lire et commence à agir — et c'est pourquoi aucune de ces routes
n'agit d'elle-même. `POST /courrier/tri` ne fait que **déposer des propositions** ;
`POST /propositions/{id}/validation` est le seul endroit du projet où un effet est produit,
et il exige un utilisateur identifié qui l'assume.
"""

from dataclasses import asdict

from fastapi import APIRouter, HTTPException, Query, status

from jurismind.agents.propositions import (
    DejaTranchee,
    PropositionIntrouvable,
    a_trancher,
    appliquer,
    rejeter,
    valider,
)
from jurismind.agents.tri import courrier_a_trier, trier
from jurismind.api.schemas import (
    DemandeRejet,
    DemandeTri,
    PropositionPublique,
    ReponseAgentPublique,
)
from jurismind.api.securite import IdentiteRequise, SessionRequise, refuser_si
from jurismind.db.models import Role

routeur = APIRouter(tags=["Courrier et décisions"])


@routeur.get("/courrier/a-trier", response_model=list[dict], summary="Le courrier sans dossier")
def a_trier(session: SessionRequise, limite: int = Query(default=20, ge=1, le=100)) -> list[dict]:
    """Les échanges qu'aucun dossier ne réclame encore."""
    return [
        {
            "communication_id": echange.id,
            "date": echange.date_echange,
            "canal": str(echange.canal),
            "expediteur": echange.expediteur,
            "objet": echange.objet,
        }
        for echange in courrier_a_trier(session, limite)
    ]


@routeur.post(
    "/courrier/tri",
    response_model=ReponseAgentPublique,
    summary="Trier le courrier entrant (F9)",
)
def tri(demande: DemandeTri, session: SessionRequise, qui: IdentiteRequise) -> ReponseAgentPublique:
    """Propose un rattachement, une priorité, un résumé et un brouillon pour chaque email.

    **Ne modifie rien.** Le rattachement et la priorité sont calculés par des règles ; seuls
    le résumé et le brouillon viennent du modèle. Compter environ 25 s par email, donc jusqu'à
    quelques minutes pour une boîte entière : l'appel est synchrone, ce qui convient à une
    démonstration mais passerait par la file `taches` en production.
    """
    refuser_si(qui.role is Role.ADMIN, "Un administrateur ne trie pas le courrier du cabinet")
    reponse = trier(session, qui.utilisateur_id, demande.limite)
    return ReponseAgentPublique(**asdict(reponse))


@routeur.get(
    "/propositions",
    response_model=list[PropositionPublique],
    summary="Ce qui attend une décision",
)
def propositions(
    session: SessionRequise, limite: int = Query(default=50, ge=1, le=200)
) -> list[PropositionPublique]:
    """Les propositions les plus sûres d'abord. `justification` dit sur quoi chacune se fonde."""
    return [PropositionPublique(**asdict(decision)) for decision in a_trancher(session, limite)]


@routeur.post(
    "/propositions/{proposition_id}/validation",
    response_model=PropositionPublique,
    summary="Valider une proposition, et produire son effet",
    responses={
        404: {"description": "Proposition inconnue, ou visant un dossier fermé à cet utilisateur"},
        409: {"description": "Un humain s'est déjà prononcé"},
    },
)
def validation(proposition_id: int, session: SessionRequise, qui: IdentiteRequise) -> PropositionPublique:
    """Le seul endroit où l'API produit un effet, et il porte le nom de qui l'a autorisé.

    Selon le type : l'échange est rattaché au dossier (et ses extraits avec lui), le brouillon
    est approuvé pour envoi — JurisMind n'envoie rien lui-même —, ou la tâche est créée dans le
    CRM. Si le CRM ne répond pas, la proposition passe à `echouee` en gardant son autorisation :
    elle se rejoue avec `POST /propositions/{id}/application`.
    """
    refuser_si(qui.role is Role.ADMIN, "Un administrateur ne tranche pas les propositions")
    try:
        return PropositionPublique(**asdict(valider(session, proposition_id, qui.utilisateur_id)))
    except PropositionIntrouvable as erreur:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(erreur)) from erreur
    except DejaTranchee as erreur:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(erreur)) from erreur


@routeur.post(
    "/propositions/{proposition_id}/rejet",
    response_model=PropositionPublique,
    summary="Rejeter une proposition",
    responses={404: {"description": "Proposition inconnue"}, 409: {"description": "Déjà tranchée"}},
)
def rejet(
    proposition_id: int, demande: DemandeRejet, session: SessionRequise, qui: IdentiteRequise
) -> PropositionPublique:
    """Rien ne se produit, et le motif est conservé : on saura pourquoi la machine s'est trompée."""
    refuser_si(qui.role is Role.ADMIN, "Un administrateur ne tranche pas les propositions")
    try:
        decision = rejeter(session, proposition_id, qui.utilisateur_id, demande.motif)
    except PropositionIntrouvable as erreur:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(erreur)) from erreur
    except DejaTranchee as erreur:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(erreur)) from erreur
    return PropositionPublique(**asdict(decision))


@routeur.post(
    "/propositions/{proposition_id}/application",
    response_model=PropositionPublique,
    summary="Rejouer une application qui avait échoué",
    responses={404: {"description": "Proposition inconnue"}, 409: {"description": "Non validée"}},
)
def application(proposition_id: int, session: SessionRequise, qui: IdentiteRequise) -> PropositionPublique:
    """Pour une proposition déjà validée dont l'effet a échoué — un CRM éteint, par exemple.

    L'autorisation humaine n'est pas redemandée : elle a déjà été donnée et elle est inscrite.
    """
    refuser_si(qui.role is Role.ADMIN, "Un administrateur ne tranche pas les propositions")
    try:
        return PropositionPublique(**asdict(appliquer(session, proposition_id)))
    except PropositionIntrouvable as erreur:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(erreur)) from erreur
    except DejaTranchee as erreur:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(erreur)) from erreur
