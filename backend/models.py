"""ORM models for inspection records."""

from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, Index, Integer, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    """Shared declarative base for all ORM models."""


class TestResult(Base):
    """One visual inspection of a unit under test.

    ``dip_switch_status`` is JSON so the five switch positions stay queryable
    without giving up the original camera string:

        {"positions": ["ON", "OFF", "ON", "ON", "OFF"], "raw": "1,PASS,ON,OFF,ON,ON,OFF"}

    ``inspection_result`` is true when the camera judgment is PASS.
    """

    __tablename__ = "test_results"
    __table_args__ = (Index("ix_test_results_timestamp", "timestamp"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    serial_number: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    dip_switch_status: Mapped[dict] = mapped_column(JSONB, nullable=False)
    inspection_result: Mapped[bool] = mapped_column(Boolean, nullable=False)
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
    )
