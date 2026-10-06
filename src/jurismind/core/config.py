"""Configuration centralisée, lue depuis les variables d'environnement et `.env`."""

from functools import lru_cache

from pydantic import SecretStr
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

    def _dsn(self, database: str, user: str, password: SecretStr) -> str:
        return (
            f"postgresql+psycopg://{user}:{password.get_secret_value()}"
            f"@{self.postgres_host}:{self.postgres_port}/{database}"
        )

    @property
    def database_url(self) -> str:
        return self._dsn(self.postgres_db, self.postgres_user, self.postgres_password)

    @property
    def app_database_url(self) -> str:
        return self._dsn(self.postgres_db, self.postgres_app_user, self.postgres_app_password)

    @property
    def legacy_database_url(self) -> str:
        return self._dsn(self.legacy_db, self.postgres_user, self.postgres_password)


@lru_cache
def get_settings() -> Settings:
    return Settings()
