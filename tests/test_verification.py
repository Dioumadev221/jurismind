"""Les contrôles appliqués aux réponses du modèle, pris un par un."""

import pytest

from jurismind.rag.verification import (
    avoue_ignorance,
    chiffres_ancres,
    chiffres_de,
    citation_verifiee,
    references_de,
    references_respectees,
)

SOURCE = (
    "Mise en demeure adressée à Ouest Africa Distribution SA\n"
    "Notre client nous indique que vous restez lui devoir la somme de 13 750 000 FCFA au titre "
    "des factures FA-2025-978 et FA-2025-143. En conséquence, nous vous mettons en demeure de "
    "régler cette somme dans un délai de 8 jours à compter de la réception de la présente."
)


# --------------------------------------------------------------------- aveux d'ignorance


@pytest.mark.parametrize(
    "reponse",
    [
        "Je ne trouve pas cette information.",
        "La question n'est pas répondu par les documents fournis.",  # formulation réelle du modèle
        "Cette information ne figure pas dans les sources.",
        "Il n'y a pas de taux de TVA dans les factures fournies.",
        "Aucune information sur le nombre de salariés.",
    ],
)
def test_les_facons_de_dire_je_ne_sais_pas_sont_reconnues(reponse: str) -> None:
    assert avoue_ignorance(reponse)


def test_une_vraie_reponse_nest_pas_prise_pour_un_aveu() -> None:
    assert not avoue_ignorance("Le débiteur dispose d'un délai de quinze jours.")
    assert not avoue_ignorance("Le montant réclamé est de 13 750 000 FCFA.")


# --------------------------------------------------------------------- références


def test_les_references_des_pieces_sont_reperees() -> None:
    assert references_de("Que dit la facture FA-2025-978 ?") == {"fa 2025 978"}
    assert references_de("l'ordonnance n° 1703/2022") == {"1703 2022"}
    assert references_de("Quel est le montant dû ?") == set()


def test_une_question_sans_reference_passe_toujours() -> None:
    assert references_respectees("Quel délai pour payer ?", SOURCE)


def test_la_reference_demandee_doit_figurer_dans_la_source() -> None:
    assert references_respectees("Montant de la facture FA-2025-978 ?", SOURCE)
    # Cas réel : le modèle répondait avec le montant d'une facture voisine.
    assert not references_respectees("Montant de la facture FA-2023-702 ?", SOURCE)


def test_une_reference_presente_dans_le_titre_suffit() -> None:
    source = "Ordonnance d'injonction de payer n° 1703/2022\nEnjoignons de payer 24 700 000 FCFA."
    assert references_respectees("Que dit l'ordonnance n° 1703/2022 ?", source)


# --------------------------------------------------------------------- citation littérale


def test_une_citation_recopiee_est_reconnue() -> None:
    assert citation_verifiee("nous vous mettons en demeure de régler cette somme", SOURCE)


def test_une_citation_legerement_reformulee_passe_encore() -> None:
    assert citation_verifiee("vous mettons en demeure de regler cette somme dans un delai", SOURCE)


def test_une_citation_inventee_est_rejetee() -> None:
    assert not citation_verifiee("La capitale du Sénégal est Dakar, chef-lieu de région.", SOURCE)


def test_une_citation_trop_courte_ne_prouve_rien() -> None:
    assert not citation_verifiee("somme", SOURCE)


# --------------------------------------------------------------------- ancrage des chiffres


def test_les_montants_et_delais_sont_extraits() -> None:
    assert chiffres_de("13 750 000 FCFA en 8 jours") == ["13750000", "8"]


def test_un_montant_de_la_source_est_ancre() -> None:
    assert chiffres_ancres("Le montant réclamé est de 13 750 000 FCFA, payable sous 8 jours.", SOURCE)


def test_un_montant_invente_nest_pas_ancre() -> None:
    assert not chiffres_ancres("Le montant réclamé est de 6 150 000 FCFA.", SOURCE)


def test_une_reponse_sans_chiffre_ne_peut_pas_etre_ancree_ainsi() -> None:
    """« La capitale du Sénégal est Dakar » ne contient aucun chiffre : ce contrôle ne la sauve pas."""
    assert not chiffres_ancres("La capitale du Sénégal est Dakar.", SOURCE)
