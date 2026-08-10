import asyncio
import calendar
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from pinendar.api.errors import domain_error_handler, error_body, validation_error_handler
from pinendar.api.router import router
from pinendar.application.state import DomainError
from pinendar.config import Settings
from pinendar.infrastructure.auth_store import AuthStore, utc_now
from pinendar.infrastructure.backups import BackupManager
from pinendar.infrastructure.catalog import HospitalCatalog
from pinendar.infrastructure.environments import EnvironmentRegistry
from pinendar.infrastructure.rate_limit import SlidingWindowRateLimiter

LOGGER = logging.getLogger(__name__)
ACCOUNT_CLEANUP_INTERVAL_SECONDS = 24 * 60 * 60


def subtract_calendar_months(value: datetime, months: int) -> datetime:
    target_month_index = value.year * 12 + value.month - 1 - months
    year, zero_based_month = divmod(target_month_index, 12)
    month = zero_based_month + 1
    day = min(value.day, calendar.monthrange(year, month)[1])
    return value.replace(year=year, month=month, day=day)


def cleanup_inactive_accounts(app: FastAPI, *, now: datetime | None = None) -> int:
    cutoff = subtract_calendar_months(
        now or utc_now(),
        app.state.settings.account_retention_months,
    )
    deleted = 0
    for account in app.state.auth_store.delete_inactive_accounts(cutoff):
        if app.state.environments.delete(account.environment_path):
            deleted += 1
        else:
            LOGGER.warning(
                "Account %s expired, but its unexpected environment path was preserved: %s",
                account.id,
                account.environment_path,
            )
    return deleted


async def cleanup_inactive_accounts_daily(app: FastAPI) -> None:
    while True:
        await asyncio.sleep(ACCOUNT_CLEANUP_INTERVAL_SECONDS)
        try:
            cleanup_inactive_accounts(app)
        except Exception:
            LOGGER.exception("Inactive account cleanup failed")


def create_app(settings: Settings | None = None) -> FastAPI:
    resolved = settings or Settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        app.state.auth_store.create_schema()
        app.state.auth_store.initialize_missing_activity()
        if resolved.bootstrap_username and resolved.bootstrap_password:
            if not app.state.auth_store.username_exists(resolved.bootstrap_username):
                app.state.auth_store.create_account(
                    resolved.bootstrap_username,
                    resolved.bootstrap_password,
                    resolved.database_path,
                )
            account = app.state.auth_store.get_account_by_username(resolved.bootstrap_username)
            assert account is not None
            environment = app.state.environments.get(account.environment_path)
            # Compatibility aliases for commands and tests which explicitly inspect the default environment.
            app.state.database = environment.database
            app.state.job_dispatcher = environment.dispatcher
        app.state.auth_store.ensure_admin(resolved.admin_username)
        cleanup_inactive_accounts(app)
        cleanup_task = asyncio.create_task(cleanup_inactive_accounts_daily(app))
        try:
            yield
        finally:
            cleanup_task.cancel()
            with suppress(asyncio.CancelledError):
                await cleanup_task
            app.state.environments.stop_all()
            app.state.auth_store.engine.dispose()

    app = FastAPI(title="Pinendar", version="0.2.0", lifespan=lifespan)
    app.state.settings = resolved
    app.state.catalog = HospitalCatalog(resolved.hospital_catalog_dir)
    app.state.auth_store = AuthStore(resolved.auth_database_path)
    app.state.backups = BackupManager(resolved.backups_dir, app.state.auth_store)
    app.state.signup_limiter = SlidingWindowRateLimiter(
        resolved.signup_requests_per_hour, 60 * 60
    )
    app.state.environments = EnvironmentRegistry(resolved, app.state.catalog)
    app.add_exception_handler(DomainError, domain_error_handler)  # type: ignore[arg-type]
    app.add_exception_handler(RequestValidationError, validation_error_handler)  # type: ignore[arg-type]
    app.include_router(router)

    @app.get("/health/live")
    def live() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/health/ready")
    def ready(request: Request) -> JSONResponse:
        if request.app.state.auth_store.ready() and request.app.state.catalog.hospitals:
            return JSONResponse({"status": "ready"})
        return JSONResponse(status_code=503, content=error_body("NOT_READY", "Servei no preparat"))

    static_dir = Path(resolved.static_dir)
    if static_dir.exists():
        app.mount("/assets", StaticFiles(directory=static_dir), name="assets")

        @app.api_route(
            "/api/{path:path}",
            methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
            include_in_schema=False,
        )
        def unknown_api(path: str) -> JSONResponse:
            return JSONResponse(status_code=404, content=error_body("ENDPOINT_NOT_FOUND", "Endpoint no trobat"))

        @app.get("/admin", include_in_schema=False)
        @app.get("/admin/", include_in_schema=False)
        def admin_frontend() -> FileResponse:
            return FileResponse(static_dir / "admin.html")

        @app.get("/{path:path}", include_in_schema=False)
        def frontend(path: str = "") -> FileResponse:
            requested = static_dir / path
            if path and requested.is_file() and requested.resolve().is_relative_to(static_dir.resolve()):
                return FileResponse(requested)
            return FileResponse(static_dir / "index.html")

    return app


app = create_app()
