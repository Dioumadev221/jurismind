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
