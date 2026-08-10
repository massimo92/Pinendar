from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="PINENDAR_", populate_by_name=True)

    database_path: Path = Path("data/pinendar.sqlite")
    auth_database_path: Path = Path("data/auth.sqlite")
    environments_dir: Path = Path("data/environments")
    backups_dir: Path = Path("data/backups")
    hospital_catalog_dir: Path = Path("data/hospitals")
    static_dir: Path = Path("public")
    bootstrap_username: str | None = None
    bootstrap_password: str | None = None
    admin_username: str = "admin"
    signup_enabled: bool = True
    signup_requests_per_hour: int = Field(default=5, ge=1, le=100)
    session_secret: str = Field(default="change-this-session-secret-before-deploying", min_length=24)
    account_retention_months: int = Field(default=6, ge=1, le=120)
    secure_cookies: bool = False
    run_job_dispatcher: bool = True
    scheduler_process_pool: bool = True
    scheduler_time_limit_seconds: float = Field(default=120, gt=0, le=300)
    scheduler_workers: int = Field(default=1, ge=1, le=16)
    scheduler_random_seed: int = Field(default=1, ge=0)
    migrate_on_startup: bool = True
    port: int = 4173
