"""Les aides partagées par les agents : lire la réponse d'un modèle sans se faire piéger.

Ces fonctions tolèrent la **forme** de ce que renvoie un modèle local — un JSON entouré de
bavardage, une clé accentuée — mais jamais le **fond** : un chiffre qui n'est pas dans les
données fournies reste un chiffre douteux.
"""

from jurismind.agents.commun import chiffres_douteux, lire_json, texte_attendu

# ------------------------------------------------------------------ lecture du JSON


def test_le_json_est_lu_meme_entoure_de_bavardage() -> None:
    assert lire_json('Voici :\n{"synthese": "ok"}\nvoilà') == {"synthese": "ok"}


def test_un_texte_sans_json_ne_casse_rien() -> None:
    assert lire_json("le modèle a répondu n'importe quoi") == {}
    assert lire_json("{ ceci n'est pas du json }") == {}


# ------------------------------------------------------------------ clé de travers


def test_la_cle_exacte_est_prise_en_premier() -> None:
    assert texte_attendu({"synthese": "A", "autre": "B"}, "synthese") == "A"


def test_une_cle_accentuee_est_acceptee() -> None:
    """Observé sur qwen2.5:3b : il « corrige » l'orthographe de la clé qu'on lui a donnée."""
    assert texte_attendu({"synthèse": "A"}, "synthese") == "A"
    assert texte_attendu({"Résumé ": "A"}, "resume") == "A"


def test_une_seule_valeur_de_texte_est_acceptee_a_defaut() -> None:
    assert texte_attendu({"reponse_finale": "A"}, "synthese") == "A"


def test_plusieurs_valeurs_sans_cle_reconnue_ne_sont_pas_devinees() -> None:
    """Deviner entre deux textes, ce serait choisir à la place du modèle."""
    assert texte_attendu({"a": "un texte", "b": "un autre"}, "synthese") == ""


def test_une_valeur_qui_nest_pas_du_texte_est_ignoree() -> None:
    assert texte_attendu({"synthese": 42}, "synthese") == ""
    assert texte_attendu({}, "synthese") == ""


# ------------------------------------------------------------------ chiffres


def test_un_chiffre_absent_des_donnees_est_douteux() -> None:
    assert chiffres_douteux("Le client doit 42 000 000 FCFA.", "enjeu : 13 750 000 FCFA")


def test_un_chiffre_present_dans_les_donnees_ne_lest_pas() -> None:
    assert not chiffres_douteux("Le client doit 13 750 000 FCFA.", "enjeu : 13 750 000 FCFA")


def test_un_separateur_different_ne_fait_pas_echouer_lancrage() -> None:
    """« 13,750,000 » et « 13 750 000 » désignent la même somme."""
    assert not chiffres_douteux("Soit 13,750,000 FCFA.", "enjeu : 13 750 000 FCFA")


def test_un_texte_sans_chiffre_nest_pas_douteux() -> None:
    """Il n'avance rien de vérifiable par ce moyen : l'écarter serait une erreur."""
    assert not chiffres_douteux("Une société dakaroise suivie en recouvrement.", "enjeu : 13 750 000")
