from datetime import datetime

from pydantic import BaseModel, ConfigDict


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class Message(BaseModel):
    message: str


class DataMeta(BaseModel):
    """Provenance attached to every market-data-derived response."""

    source: str
    is_sample: bool
    attribution: str
    stale: bool = False
    fetched_at: datetime | None = None
