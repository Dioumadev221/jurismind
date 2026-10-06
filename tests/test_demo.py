"""Le client HTTP de la démonstration.

La démo ne touche jamais la base : elle passe par l'API avec le jeton de l'utilisateur. Ces
tests fixent les deux comportements qui comptent pour celui qui fait la démonstration — le
jeton est bien transmis, et une API éteinte donne un message qu'on peut lire plutôt qu'une
trace d'erreur.
"""

import httpx
import pytest

from jurismind.demo.client import Api, ApiIndisponible, ApiRefuse


def transport(gestionnaire: object) -> httpx.MockTransport:
    return httpx.MockTransport(gestionnaire)  # type: ignore[arg-type]


def brancher(monkeypatch: pytest.MonkeyPatch, gestionnaire: object) -> list[httpx.Request]:
    """Remplace le transport HTTP et note les requêtes parties."""
    vues: list[httpx.Request] = []

    def enregistrer(requete: httpx.Request) -> httpx.Response:
        vues.append(requete)
        return gestionnaire(requete)  # type: ignore[operator]

    vrai_init = httpx.Client.__init__

    def init(self: httpx.Client, *args: object, **options: object) -> None:
        options["transport"] = transport(enregistrer)
        vrai_init(self, *args, **options)  # type: ignore[arg-type]

    monkeypatch.setattr(httpx.Client, "__init__", init)
    return vues


def test_le_jeton_accompagne_chaque_appel(monkeypatch: pytest.MonkeyPatch) -> None:
    vues = brancher(monkeypatch, lambda requete: httpx.Response(200, json={"ok": True}))
    assert Api("http://api.test", jeton="abc").get("/dossiers") == {"ok": True}
    assert vues[0].headers["Authorization"] == "Bearer abc"


def test_sans_jeton_aucun_en_tete_nest_ajoute(monkeypatch: pytest.MonkeyPatch) -> None:
    vues = brancher(monkeypatch, lambda requete: httpx.Response(200, json={}))
    Api("http://api.test").get("/sante")
    assert "Authorization" not in vues[0].headers


def test_une_api_eteinte_donne_un_message_lisible(monkeypatch: pytest.MonkeyPatch) -> None:
    def tombe(requete: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refusée", request=requete)

    brancher(monkeypatch, tombe)
    with pytest.raises(ApiIndisponible, match="ne répond pas"):
        Api("http://api.test").sante()


def test_une_erreur_metier_porte_son_code_et_son_detail(monkeypatch: pytest.MonkeyPatch) -> None:
    brancher(
        monkeypatch,
        lambda requete: httpx.Response(404, json={"detail": "Dossier D2026-0027 introuvable"}),
    )
    with pytest.raises(ApiRefuse) as capture:
        Api("http://api.test", jeton="abc").get("/dossiers/D2026-0027")
    assert capture.value.code == 404
    assert "introuvable" in capture.value.detail


def test_une_erreur_sans_json_ne_casse_pas_la_demo(monkeypatch: pytest.MonkeyPatch) -> None:
    brancher(monkeypatch, lambda requete: httpx.Response(502, text="<html>passerelle</html>"))
    with pytest.raises(ApiRefuse) as capture:
        Api("http://api.test").get("/dossiers")
    assert capture.value.code == 502


def test_la_connexion_envoie_le_couple_attendu(monkeypatch: pytest.MonkeyPatch) -> None:
    vues = brancher(monkeypatch, lambda requete: httpx.Response(200, json={"jeton": "x"}))
    Api("http://api.test").connexion("m.dieng@test", "secret")
    assert vues[0].method == "POST"
    assert vues[0].url.path == "/connexion"
