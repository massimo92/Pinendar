from __future__ import annotations

import re
import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError
from sqlalchemy import Boolean, DateTime, Integer, String, create_engine, event, select, text
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker

from pinendar.application.state import DomainError

USERNAME_PATTERN = re.compile(r"^[a-z0-9][a-z0-9._-]{2,39}$")


class AuthBase(DeclarativeBase):
    pass


def utc_now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


class Account(AuthBase):
    __tablename__ = "accounts"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    username: Mapped[str] = mapped_column(String(40), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String, nullable=False)
    recovery_hash: Mapped[str] = mapped_column(String, nullable=False)
    environment_path: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    session_version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    disabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, nullable=False)


class AccountOnboarding(AuthBase):
    __tablename__ = "account_onboarding"

    account_id: Mapped[str] = mapped_column(String, primary_key=True)
    guide_prompt_seen_at: Mapped[datetime | None] = mapped_column(DateTime)


class AccountActivity(AuthBase):
    __tablename__ = "account_activity"

    account_id: Mapped[str] = mapped_column(String, primary_key=True)
    last_active_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


@dataclass(frozen=True)
class AccountIdentity:
    id: str
    username: str
    environment_path: Path
    session_version: int
    disabled: bool


class AuthStore:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self.engine = create_engine(
            f"sqlite:///{path}", connect_args={"check_same_thread": False}, future=True
        )
        event.listen(self.engine, "connect", self._configure_sqlite)
        self.session_factory = sessionmaker(bind=self.engine, expire_on_commit=False)
        self.password_hasher = PasswordHasher()

    @staticmethod
    def _configure_sqlite(dbapi_connection: object, _connection_record: object) -> None:
        cursor = dbapi_connection.cursor()  # type: ignore[attr-defined]
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA busy_timeout=5000")
        cursor.close()

    def create_schema(self) -> None:
        AuthBase.metadata.create_all(self.engine)

    def ready(self) -> bool:
        with self.engine.connect() as connection:
            result = connection.execute(text("SELECT 1")).scalar_one()
            return bool(result == 1)

    @staticmethod
    def normalize_username(username: str) -> str:
        normalized = username.strip().lower()
        if not USERNAME_PATTERN.fullmatch(normalized):
            raise DomainError(
                "INVALID_USERNAME",
                "L’usuari ha de tenir entre 3 i 40 caràcters: lletres, números, punt, guió o guió baix",
                field="username",
            )
        return normalized

    @staticmethod
    def validate_password(password: str) -> None:
        if len(password) < 8:
            raise DomainError(
                "WEAK_PASSWORD",
                "La contrasenya ha de tenir almenys 8 caràcters",
                field="password",
            )

    @staticmethod
    def recovery_code() -> str:
        raw = secrets.token_hex(16).upper()
        return "-".join(raw[index : index + 4] for index in range(0, len(raw), 4))

    @staticmethod
    def identity(account: Account) -> AccountIdentity:
        return AccountIdentity(
            id=account.id,
            username=account.username,
            environment_path=Path(account.environment_path),
            session_version=account.session_version,
            disabled=account.disabled,
        )

    def username_exists(self, username: str) -> bool:
        normalized = self.normalize_username(username)
        with self.session_factory() as session:
            return session.scalar(select(Account.id).where(Account.username == normalized)) is not None

    def count_accounts(self) -> int:
        with self.session_factory() as session:
            return len(session.scalars(select(Account.id)).all())

    def create_account(self, username: str, password: str, environment_path: Path) -> tuple[AccountIdentity, str]:
        normalized = self.normalize_username(username)
        self.validate_password(password)
        recovery_code = self.recovery_code()
        with self.session_factory.begin() as session:
            if session.scalar(select(Account.id).where(Account.username == normalized)):
                raise DomainError("USERNAME_EXISTS", "Aquest usuari ja existeix", field="username")
            account = Account(
                id=str(uuid.uuid4()),
                username=normalized,
                password_hash=self.password_hasher.hash(password),
                recovery_hash=self.password_hasher.hash(recovery_code),
                environment_path=str(environment_path.resolve()),
            )
            session.add(account)
            session.flush()
            session.add(AccountActivity(account_id=account.id, last_active_at=utc_now()))
            return self.identity(account), recovery_code

    def authenticate(self, username: str, password: str) -> AccountIdentity:
        normalized = self.normalize_username(username)
        with self.session_factory.begin() as session:
            account = session.scalar(select(Account).where(Account.username == normalized))
            if not account or account.disabled or not self._verify(account.password_hash, password):
                raise DomainError("INVALID_CREDENTIALS", "Usuari o contrasenya incorrectes")
            if self.password_hasher.check_needs_rehash(account.password_hash):
                account.password_hash = self.password_hasher.hash(password)
            self._touch_activity(session, account.id, utc_now(), force=True)
            return self.identity(account)

    def get_account(self, account_id: str) -> AccountIdentity | None:
        with self.session_factory() as session:
            account = session.get(Account, account_id)
            return self.identity(account) if account else None

    def get_account_by_username(self, username: str) -> AccountIdentity | None:
        normalized = self.normalize_username(username)
        with self.session_factory() as session:
            account = session.scalar(select(Account).where(Account.username == normalized))
            return self.identity(account) if account else None

    def recover(self, username: str, recovery_code: str, new_password: str) -> tuple[AccountIdentity, str]:
        normalized = self.normalize_username(username)
        self.validate_password(new_password)
        with self.session_factory.begin() as session:
            account = session.scalar(select(Account).where(Account.username == normalized))
            if not account or account.disabled or not self._verify(account.recovery_hash, recovery_code.strip().upper()):
                raise DomainError("INVALID_RECOVERY_CODE", "Usuari o clau de recuperació incorrectes")
            next_code = self.recovery_code()
            account.password_hash = self.password_hasher.hash(new_password)
            account.recovery_hash = self.password_hasher.hash(next_code)
            account.session_version += 1
            self._touch_activity(session, account.id, utc_now(), force=True)
            session.flush()
            return self.identity(account), next_code

    def rotate_recovery_code(self, account_id: str) -> str:
        with self.session_factory.begin() as session:
            account = session.get(Account, account_id)
            if not account or account.disabled:
                raise DomainError("ACCOUNT_NOT_FOUND", "Usuari no trobat")
            next_code = self.recovery_code()
            account.recovery_hash = self.password_hasher.hash(next_code)
            return next_code

    def guide_onboarding_pending(self, account_id: str) -> bool:
        with self.session_factory() as session:
            onboarding = session.get(AccountOnboarding, account_id)
            return onboarding is None or onboarding.guide_prompt_seen_at is None

    def mark_guide_onboarding_seen(self, account_id: str) -> None:
        with self.session_factory.begin() as session:
            if not session.get(Account, account_id):
                raise DomainError("ACCOUNT_NOT_FOUND", "Usuari no trobat")
            onboarding = session.get(AccountOnboarding, account_id)
            if onboarding:
                onboarding.guide_prompt_seen_at = utc_now()
            else:
                session.add(
                    AccountOnboarding(
                        account_id=account_id,
                        guide_prompt_seen_at=utc_now(),
                    )
                )

    def initialize_missing_activity(self) -> None:
        now = utc_now()
        with self.session_factory.begin() as session:
            tracked_ids = set(session.scalars(select(AccountActivity.account_id)))
            for account_id in session.scalars(select(Account.id)):
                if account_id not in tracked_ids:
                    session.add(AccountActivity(account_id=account_id, last_active_at=now))

    def touch_activity(self, account_id: str) -> bool:
        with self.session_factory.begin() as session:
            if not session.get(Account, account_id):
                return False
            self._touch_activity(session, account_id, utc_now())
            return True

    def delete_inactive_accounts(self, cutoff: datetime) -> list[AccountIdentity]:
        with self.session_factory.begin() as session:
            accounts = list(
                session.scalars(
                    select(Account)
                    .join(AccountActivity, AccountActivity.account_id == Account.id)
                    .where(AccountActivity.last_active_at < cutoff)
                )
            )
            identities = [self.identity(account) for account in accounts]
            for account in accounts:
                activity = session.get(AccountActivity, account.id)
                onboarding = session.get(AccountOnboarding, account.id)
                if activity:
                    session.delete(activity)
                if onboarding:
                    session.delete(onboarding)
                session.delete(account)
            return identities

    def reset_password(self, username: str, password: str) -> AccountIdentity:
        normalized = self.normalize_username(username)
        self.validate_password(password)
        with self.session_factory.begin() as session:
            account = session.scalar(select(Account).where(Account.username == normalized))
            if not account:
                raise DomainError("ACCOUNT_NOT_FOUND", "Usuari no trobat")
            account.password_hash = self.password_hasher.hash(password)
            account.session_version += 1
            session.flush()
            return self.identity(account)

    @staticmethod
    def _touch_activity(
        session: Session,
        account_id: str,
        now: datetime,
        *,
        force: bool = False,
    ) -> None:
        activity = session.get(AccountActivity, account_id)
        if not activity:
            session.add(AccountActivity(account_id=account_id, last_active_at=now))
        elif force or activity.last_active_at <= now - timedelta(hours=1):
            activity.last_active_at = now

    @staticmethod
    def _verify(encoded: str, value: str) -> bool:
        try:
            return bool(PasswordHasher().verify(encoded, value))
        except (VerifyMismatchError, InvalidHashError):
            return False
