from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "黃金珠寶進銷存暨營運管理系統"
    environment: str = "development"
    database_url: str = "postgresql+psycopg://postgres:postgres@localhost:5432/gold_jewelry_erp"
    app_maintenance_mode: bool = False

    # Single-administrator authentication. Values are supplied only through
    # the deployment environment, never committed to the repository.
    admin_username: str = ""
    admin_password: str = ""
    session_secret_key: str = ""
    session_max_age_seconds: int = 43200
    session_cookie_name: str = "gold_erp_session"
    session_cookie_secure: bool = True

    @property
    def auth_configured(self) -> bool:
        return bool(
            self.admin_username.strip()
            and len(self.admin_password) >= 12
            and len(self.session_secret_key) >= 32
        )

    @property
    def auth_enabled(self) -> bool:
        return self.environment.lower() == "production" or any(
            (self.admin_username, self.admin_password, self.session_secret_key)
        )

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")


settings = Settings()
