"""Pydantic models for the HTTP and WebSocket payloads."""

import re
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator


class DipSwitchStatus(BaseModel):
    """Five DIP positions plus the camera's original ASCII line."""

    positions: list[str]
    raw: str


class TestResultRead(BaseModel):
    """A stored inspection, ready to send to the dashboard."""

    id: int
    serial_number: str
    dip_switch_status: DipSwitchStatus
    inspection_result: bool
    timestamp: datetime

    model_config = ConfigDict(from_attributes=True)


class InspectionRequest(BaseModel):
    """Optional serial supplied by the operator. The API generates one when omitted."""

    serial_number: str | None = Field(default=None, max_length=64)

    @field_validator("serial_number")
    @classmethod
    def _clean_serial(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        if not cleaned:
            return None
        if not re.fullmatch(r"[A-Za-z0-9_-]+", cleaned):
            raise ValueError(
                "Serial number may contain only letters, numbers, '_' and '-'"
            )
        return cleaned


class HealthStatus(BaseModel):
    camera: str
    database: str


class ServiceInfo(BaseModel):
    service: str
    docs: str
    health: str
