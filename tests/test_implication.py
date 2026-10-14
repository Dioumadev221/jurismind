"""Le cinquième contrôle : la source citée établit-elle vraiment ce qui est affirmé ?

Aucun test de ce fichier n'appelle de modèle. Le juge est remplacé par un double qui rend le
verdict choisi par le test, et qui **note l'invite reçue** : c'est ainsi qu'on vérifie qu'on
ne le dérange pas pour rien, ce qui est la moitié de la décision (ADR 0010).
"""

from typing import Any

import pytest

from jurismind.rag.implication import source_soutient


class JugeSimule:
    """Rend le verdict choisi par le test, et retient ce qu'on lui a demandé."""

    def __init__(self, verdict: Any) -> None:
        self.verdict = verdict
        self.invites: list[str] = []

    def invoke(self, invite: str) -> Any:
        self.invites.append(invite)
        return type("Message", (), {"content": self.verdict})()


class JugeAbsent:
    """Échoue si on l'appelle : le service de modèle est tombé."""

    def invoke(self, invite: str) -> Any:
        raise ConnectionError("ollama injoignable")


def brancher(monkeypatch: pytest.MonkeyPatch, juge: Any) -> None:
    monkeypatch.setattr("jurismind.rag.implication.modele_chat", lambda *a, **k: juge)


SOURCE = (
    "Mise en demeure adressée à Djoloff Distribution GIE\n"
    "Nous vous mettons en demeure de régler cette somme dans un délai de huit jours."
)


def test_une_affirmation_soutenue_passe(monkeypatch: pytest.MonkeyPatch) -> None:
    brancher(monkeypatch, JugeSimule('{"soutenue": true}'))
    assert source_soutient("La mise en demeure accorde un délai de huit jours.", SOURCE)


def test_une_affirmation_etrangere_a_la_source_est_ecartee(monkeypatch: pytest.MonkeyPatch) -> None:
    """Le cas qui a motivé ce contrôle : vrai dans le monde, absent de la pièce."""
    brancher(monkeypatch, JugeSimule('{"soutenue": false}'))
    assert not source_soutient("La capitale du Sénégal est Dakar.", SOURCE)


def test_la_source_et_laffirmation_sont_toutes_deux_soumises_au_juge(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    juge = JugeSimule('{"soutenue": true}')
    brancher(monkeypatch, juge)
    source_soutient("La mise en demeure accorde un délai de huit jours.", SOURCE)

    assert len(juge.invites) == 1
    invite = juge.invites[0]
    assert "huit jours" in invite
    assert "Djoloff Distribution GIE" in invite
    # La règle qui rattrape « Dakar » doit être dans l'invite, sinon le contrôle ne sert à rien.
    assert "absente de la source" in invite


@pytest.mark.parametrize(
    "verdict",
    [
        'Voici mon analyse : {"soutenue": false} — la source ne le dit pas.',
        '```json\n{"soutenue": false}\n```',
    ],
)
def test_un_verdict_entoure_de_texte_est_quand_meme_lu(monkeypatch: pytest.MonkeyPatch, verdict: str) -> None:
    brancher(monkeypatch, JugeSimule(verdict))
    assert not source_soutient("La capitale du Sénégal est Dakar.", SOURCE)


def test_un_verdict_illisible_ecarte_la_reponse(monkeypatch: pytest.MonkeyPatch) -> None:
    """Le doute compte contre la réponse : un silence de trop plutôt qu'une invention."""
    brancher(monkeypatch, JugeSimule("le modèle a répondu n'importe quoi"))
    assert not source_soutient("La capitale du Sénégal est Dakar.", SOURCE)


def test_un_verdict_contradictoire_ne_tranche_rien(monkeypatch: pytest.MonkeyPatch) -> None:
    brancher(monkeypatch, JugeSimule('{"soutenue": true} mais aussi {"soutenue": false}'))
    assert not source_soutient("Peu importe.", SOURCE)


def test_un_juge_injoignable_ne_valide_rien(monkeypatch: pytest.MonkeyPatch) -> None:
    """Un service tombé ne doit jamais faire passer ce qu'il aurait dû examiner."""
    brancher(monkeypatch, JugeAbsent())
    assert not source_soutient("La capitale du Sénégal est Dakar.", SOURCE)


def test_sans_source_le_juge_nest_meme_pas_appele(monkeypatch: pytest.MonkeyPatch) -> None:
    juge = JugeSimule('{"soutenue": true}')
    brancher(monkeypatch, juge)
    assert not source_soutient("Une affirmation sans pièce.", "")
    assert not source_soutient("", SOURCE)
    assert juge.invites == []
