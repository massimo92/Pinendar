from __future__ import annotations

from datetime import UTC, date, datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


def utc_now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


class AppSettings(Base):
    __tablename__ = "settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    language: Mapped[str] = mapped_column(String(2), default="ca")
    color_scheme_version: Mapped[int] = mapped_column(Integer, default=4)
    planning_revision: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, onupdate=utc_now)


class Hospital(Base):
    __tablename__ = "hospitals"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    catalog_id: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    name: Mapped[str | None] = mapped_column(String)
    address: Mapped[str | None] = mapped_column(String)
    location_known: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)


class Agenda(Base):
    __tablename__ = "agendas"
    __table_args__ = (
        CheckConstraint("priority BETWEEN 1 AND 4", name="ck_agendas_priority"),
        CheckConstraint("shift IN ('morning', 'afternoon')", name="ck_agendas_shift"),
        CheckConstraint("load_percentage IN (50, 100)", name="ck_agendas_load_percentage"),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    hospital_catalog_id: Mapped[str] = mapped_column(
        ForeignKey("hospitals.catalog_id", ondelete="RESTRICT"), nullable=False
    )
    telematic: Mapped[bool] = mapped_column(Boolean, default=False)
    shift: Mapped[str] = mapped_column(String(9), default="morning", nullable=False)
    color: Mapped[str] = mapped_column(String, nullable=False)
    priority: Mapped[int] = mapped_column(Integer, default=3, nullable=False)
    load_percentage: Mapped[int] = mapped_column(Integer, default=100, nullable=False)
    archived_at: Mapped[date | None] = mapped_column(Date)


class Coverage(Base):
    __tablename__ = "coverage"
    __table_args__ = (UniqueConstraint("agenda_id", "weekday"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    agenda_id: Mapped[str] = mapped_column(ForeignKey("agendas.id", ondelete="CASCADE"), nullable=False)
    weekday: Mapped[int] = mapped_column(Integer, nullable=False)
    slots: Mapped[int] = mapped_column(Integer, default=0)


class AgendaRecurrence(Base):
    __tablename__ = "agenda_recurrences"
    __table_args__ = (
        CheckConstraint("slots = 1", name="ck_agenda_recurrences_one_slot"),
        UniqueConstraint("agenda_id", "ordinal", "weekday"),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True)
    agenda_id: Mapped[str] = mapped_column(ForeignKey("agendas.id", ondelete="CASCADE"), nullable=False)
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    weekday: Mapped[int] = mapped_column(Integer, nullable=False)
    slots: Mapped[int] = mapped_column(Integer, default=1, nullable=False)


class Member(Base):
    __tablename__ = "members"
    __table_args__ = (
        CheckConstraint("work_pattern_weeks BETWEEN 1 AND 5", name="ck_members_work_pattern_weeks"),
        CheckConstraint("management_quota BETWEEN 0 AND 5", name="ck_members_management_quota"),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    normalized_name: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    email: Mapped[str] = mapped_column(String, nullable=False)
    normalized_email: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    color: Mapped[str] = mapped_column(String, nullable=False)
    management_quota: Mapped[int] = mapped_column(Integer, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    work_pattern_weeks: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    archived_at: Mapped[date | None] = mapped_column(Date)


class MemberAlias(Base):
    __tablename__ = "member_aliases"
    __table_args__ = (UniqueConstraint("member_id", "normalized_alias"),)

    id: Mapped[str] = mapped_column(String, primary_key=True)
    member_id: Mapped[str] = mapped_column(ForeignKey("members.id", ondelete="CASCADE"), nullable=False)
    alias: Mapped[str] = mapped_column(String, nullable=False)
    normalized_alias: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, nullable=False)


class MemberStatusChange(Base):
    __tablename__ = "member_status_changes"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    member_id: Mapped[str] = mapped_column(ForeignKey("members.id", ondelete="CASCADE"), nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False)
    changed_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, nullable=False)


class MemberAvailableDay(Base):
    __tablename__ = "member_available_days"
    __table_args__ = (
        UniqueConstraint("member_id", "week_index", "weekday"),
        CheckConstraint("week_index BETWEEN 0 AND 4", name="ck_member_available_days_week_index"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    member_id: Mapped[str] = mapped_column(ForeignKey("members.id", ondelete="CASCADE"), nullable=False)
    week_index: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    weekday: Mapped[int] = mapped_column(Integer, nullable=False)


class MemberTeleDay(Base):
    __tablename__ = "member_tele_days"
    __table_args__ = (
        UniqueConstraint("member_id", "week_index", "weekday"),
        CheckConstraint("week_index BETWEEN 0 AND 4", name="ck_member_tele_days_week_index"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    member_id: Mapped[str] = mapped_column(ForeignKey("members.id", ondelete="CASCADE"), nullable=False)
    week_index: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    weekday: Mapped[int] = mapped_column(Integer, nullable=False)


class MemberCapability(Base):
    __tablename__ = "member_capabilities"
    __table_args__ = (UniqueConstraint("member_id", "agenda_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    member_id: Mapped[str] = mapped_column(ForeignKey("members.id", ondelete="CASCADE"), nullable=False)
    agenda_id: Mapped[str] = mapped_column(ForeignKey("agendas.id", ondelete="CASCADE"), nullable=False)


class MemberAgendaPreference(Base):
    __tablename__ = "member_agenda_preferences"
    __table_args__ = (
        UniqueConstraint("member_id", "agenda_id"),
        CheckConstraint("preference IN (-1, 1)", name="ck_member_agenda_preferences_value"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    member_id: Mapped[str] = mapped_column(ForeignKey("members.id", ondelete="CASCADE"), nullable=False)
    agenda_id: Mapped[str] = mapped_column(ForeignKey("agendas.id", ondelete="CASCADE"), nullable=False)
    preference: Mapped[int] = mapped_column(Integer, nullable=False)


class FixedRule(Base):
    __tablename__ = "fixed_rules"
    __table_args__ = (UniqueConstraint("member_id", "weekday"),)

    id: Mapped[str] = mapped_column(String, primary_key=True)
    member_id: Mapped[str] = mapped_column(ForeignKey("members.id", ondelete="CASCADE"), nullable=False)
    agenda_id: Mapped[str] = mapped_column(ForeignKey("agendas.id", ondelete="CASCADE"), nullable=False)
    weekday: Mapped[int] = mapped_column(Integer, nullable=False)


class Absence(Base):
    __tablename__ = "absences"
    __table_args__ = (
        CheckConstraint("category IN ('vacances', 'postguardia')", name="ck_absences_category"),
        UniqueConstraint("member_id", "category", "start", "end"),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True)
    generation_job_id: Mapped[str | None] = mapped_column(
        ForeignKey("generation_jobs.id", ondelete="SET NULL")
    )
    member_id: Mapped[str] = mapped_column(ForeignKey("members.id", ondelete="CASCADE"), nullable=False)
    category: Mapped[str] = mapped_column(String, default="vacances", nullable=False)
    start: Mapped[date] = mapped_column(Date, nullable=False)
    end: Mapped[date] = mapped_column(Date, nullable=False)
    notes: Mapped[str] = mapped_column(Text, default="")


class Holiday(Base):
    __tablename__ = "holidays"

    date: Mapped[date] = mapped_column(Date, primary_key=True)


class Guard(Base):
    __tablename__ = "guards"
    __table_args__ = (UniqueConstraint("date"),)

    id: Mapped[str] = mapped_column(String, primary_key=True)
    generation_job_id: Mapped[str | None] = mapped_column(
        ForeignKey("generation_jobs.id", ondelete="SET NULL")
    )
    member_id: Mapped[str] = mapped_column(ForeignKey("members.id", ondelete="CASCADE"), nullable=False)
    date: Mapped[date] = mapped_column(Date, nullable=False)


class GuardTransfer(Base):
    __tablename__ = "guard_transfers"
    __table_args__ = (
        CheckConstraint(
            "from_member_id IS NOT NULL OR to_member_id IS NOT NULL",
            name="ck_guard_transfers_has_internal_party",
        ),
        CheckConstraint(
            "operation_kind IN ('cession', 'exchange')",
            name="ck_guard_transfers_operation_kind",
        ),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True)
    operation_id: Mapped[str] = mapped_column(String, nullable=False)
    operation_kind: Mapped[str] = mapped_column(String, nullable=False)
    guard_date: Mapped[date] = mapped_column(Date, nullable=False)
    from_member_id: Mapped[str | None] = mapped_column(
        ForeignKey("members.id", ondelete="RESTRICT")
    )
    to_member_id: Mapped[str | None] = mapped_column(
        ForeignKey("members.id", ondelete="RESTRICT")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, nullable=False)
    note: Mapped[str] = mapped_column(Text, default="", nullable=False)
    impact_json: Mapped[str] = mapped_column(Text, default="{}", nullable=False)


class PlanningEvent(Base):
    __tablename__ = "planning_events"
    __table_args__ = (
        CheckConstraint("load_percentage IN (0, 50, 100)", name="ck_planning_events_load"),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True)
    generation_job_id: Mapped[str | None] = mapped_column(
        ForeignKey("generation_jobs.id", ondelete="SET NULL")
    )
    date: Mapped[date] = mapped_column(Date, nullable=False)
    member_id: Mapped[str] = mapped_column(ForeignKey("members.id", ondelete="RESTRICT"), nullable=False)
    agenda_id: Mapped[str | None] = mapped_column(ForeignKey("agendas.id", ondelete="RESTRICT"))
    kind: Mapped[str] = mapped_column(String, default="assigned")
    load_percentage: Mapped[int] = mapped_column(Integer, default=100)
    locked: Mapped[bool] = mapped_column(Boolean, default=False)
    fixed: Mapped[bool] = mapped_column(Boolean, default=False)
    extra: Mapped[bool] = mapped_column(Boolean, default=False)
    manually_modified: Mapped[bool] = mapped_column(Boolean, default=False)
    management: Mapped[bool] = mapped_column(Boolean, default=False)


class Vacancy(Base):
    __tablename__ = "vacancies"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    generation_job_id: Mapped[str | None] = mapped_column(
        ForeignKey("generation_jobs.id", ondelete="SET NULL")
    )
    date: Mapped[date] = mapped_column(Date, nullable=False)
    agenda_id: Mapped[str] = mapped_column(ForeignKey("agendas.id", ondelete="RESTRICT"), nullable=False)


class GenerationJob(Base):
    __tablename__ = "generation_jobs"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    status: Mapped[str] = mapped_column(String, nullable=False, default="queued")
    start_month: Mapped[str] = mapped_column(String(7), nullable=False)
    end_month: Mapped[str] = mapped_column(String(7), nullable=False)
    start_date: Mapped[date | None] = mapped_column(Date)
    end_date: Mapped[date | None] = mapped_column(Date)
    input_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    input_snapshot: Mapped[str] = mapped_column(Text, nullable=False)
    result_json: Mapped[str | None] = mapped_column(Text)
    error_code: Mapped[str | None] = mapped_column(String)
    error_message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)
    started_at: Mapped[datetime | None] = mapped_column(DateTime)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime)


Assignment = PlanningEvent


Index("ix_planning_events_date", PlanningEvent.date)
Index("ix_jobs_status", GenerationJob.status)
Index("ix_guard_transfers_created", GuardTransfer.created_at)
