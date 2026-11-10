from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field


class ContractBase(BaseModel):
    vendor_name: str = Field(min_length=1, max_length=255)
    title: str = Field(min_length=1, max_length=255)
    renewal_date: date | None = None
    notice_period_days: int | None = Field(default=None, ge=0)
    source_clause: str | None = None


class ContractRead(ContractBase):
    model_config = ConfigDict(from_attributes=True)
    id: int
    created_at: datetime
    updated_at: datetime


class ObligationBase(BaseModel):
    contract_id: int
    title: str = Field(min_length=1, max_length=255)
    description: str | None = None
    due_date: date | None = None
    owner: str | None = None
    source_clause: str | None = None
    review_status: str = "pending_review"
    is_completed: bool = False


class ObligationRead(ObligationBase):
    model_config = ConfigDict(from_attributes=True)
    id: int
    created_at: datetime
    updated_at: datetime
