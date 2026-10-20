"""Configuration centralisée, lue depuis les variables d'environnement et `.env`."""

from datetime import date
from functools import lru_cache

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    postgres_user: str = "jurismind"
    postgres_password: SecretStr = SecretStr("jurismind")
    postgres_db: str = "jurismind"
    # Utilisateur PostgreSQL de l'application, soumis aux règles d'isolation.
    postgres_app_user: str = "jurismind_app"
    postgres_app_password: SecretStr = SecretStr("jurismind_app")
    postgres_host: str = "localhost"
    postgres_port: int = 5432
    legacy_db: str = "legacy"

    ollama_base_url: str = "http://localhost:11434"

    # --- Documents du cabinet ---
    # Racine du serveur de fichiers où sont rangés les documents des dossiers.
    documents_dir: str = "data/cabinet/documents"
    # Chemin de tesseract.exe s'il n'est pas dans le PATH (Windows).
    tesseract_exe: str | None = None
    # Dossier contenant les langues (fra.traineddata), si elles ne sont pas installées
    # avec Tesseract : récupérable avec `python -m jurismind.ingestion.langues`.
    tessdata_dir: str | None = "data/tessdata"

    # --- CRM du cabinet ---
    crm_base_url: str = "http://localhost:8100"
    crm_api_key: SecretStr = SecretStr("crm-dev-key")

    # --- API REST ---
    # Clé de signature des jetons. La valeur par défaut ne sert qu'au développement :
    # en production elle vient de l'environnement, et un redémarrage avec une autre clé
    # invalide tous les jetons en circulation (ce qui est le comportement voulu).
    api_secret: SecretStr = SecretStr("jurismind-dev-secret-a-remplacer")
    # Durée de vie d'un jeton : une journée de travail.
    api_duree_jeton_minutes: int = 480

    # --- Modèles ---
    llm_fournisseur: str = "ollama"  # ollama | openai
    modele_rapide: str = "qwen2.5:3b"  # chat, routage, tri des emails
    modele_qualite: str = "qwen2.5:latest"  # extraction, résumés (en tâche de fond)
    modele_embeddings: str = "bge-m3"
    openai_api_key: SecretStr | None = None
    # Fichier où consigner chaque appel aux modèles (invite et réponse), pour qu'une
    # démonstration publique puisse les rejouer sans modèle : voir `jurismind.llm.rejeu`.
    llm_enregistrement: str | None = None
    # Ce que rejoue le fournisseur `demo`.
    llm_rejeu: str = "demo/enregistrements.jsonl"

    # --- Démonstration publique ---
    # Active l'entrée sans mot de passe sur les comptes de démonstration, le bandeau
    # « cabinet simulé » et les questions proposées. Jamais en production.
    demo: bool = False
    # Le « jour » du cabinet. Vide : la date réelle. Une démonstration fige la date de son
    # corpus, sinon chaque délai simulé finit par être échu et l'échéancier se vide.
    date_du_cabinet: date | None = None
    # Où mène le bouton « Un projet pour votre cabinet ? » de la page d'accueil.
    contact_url: str | None = None

    # Chaîne de connexion unique (Neon, Render…). Prioritaire sur les champs ci-dessus quand
    # elle est fournie ; le rôle de l'application reprend le même hôte et la même base.
    database_url_externe: str | None = Field(default=None, alias="DATABASE_URL")

    def _dsn(self, database: str, user: str, password: SecretStr) -> str:
        if self.database_url_externe:
            base = None if database == self.postgres_db else database
            return _remplacer_compte(self.database_url_externe, base, user, password)
        return (
            f"postgresql+psycopg://{user}:{password.get_secret_value()}"
            f"@{self.postgres_host}:{self.postgres_port}/{database}"
        )

    @property
    def database_url(self) -> str:
        if self.database_url_externe:
            return _avec_pilote(self.database_url_externe)
        return self._dsn(self.postgres_db, self.postgres_user, self.postgres_password)

    @property
    def app_database_url(self) -> str:
        return self._dsn(self.postgres_db, self.postgres_app_user, self.postgres_app_password)

    @property
    def legacy_database_url(self) -> str:
        return self._dsn(self.legacy_db, self.postgres_user, self.postgres_password)


def _avec_pilote(adresse: str) -> str:
    """`postgresql://` (ce que donnent Neon et Render) → le pilote psycopg 3 du projet."""
    for prefixe in ("postgresql+psycopg://", "postgresql://", "postgres://"):
        if adresse.startswith(prefixe):
            return "postgresql+psycopg://" + adresse[len(prefixe) :]
    return adresse


def _remplacer_compte(adresse: str, database: str | None, user: str, password: SecretStr) -> str:
    """Même serveur, mêmes options (`sslmode`…), autre compte — et autre base au besoin.

    Le rôle de l'application n'a pas de chaîne à lui chez l'hébergeur : on la dérive de celle
    du propriétaire, en ne changeant que ce qui doit changer.
    """
    from sqlalchemy.engine import make_url

    url = make_url(_avec_pilote(adresse))
    if database is not None:
        url = url.set(database=database)
    return url.set(username=user, password=password.get_secret_value()).render_as_string(hide_password=False)


@lru_cache
def get_settings() -> Settings:
    return Settings()
