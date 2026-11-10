"""Database operations shared by MCP and future API endpoints."""
from datetime import date
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy import select

from app.database import SessionLocal
from app.models import Contract, Obligation
from app.deadlines import deadline_status, workspace_today

NonEmpty = Annotated[str, Field(min_length=1, max_length=255)]


class Inputs(BaseModel):
    model_config = ConfigDict(strict=True, str_strip_whitespace=True, extra="forbid")

    @field_validator("*", mode="before")
    @classmethod
    def reject_blank(cls, value):
        if isinstance(value, str) and not value.strip():
            raise ValueError("Strings must not be blank")
        return value


class ContractInput(Inputs):
    vendor_name: NonEmpty
    title: NonEmpty
    renewal_date: str
    notice_period_days: Annotated[int, Field(ge=0)]
    source_clause: str | None = None

    @field_validator("renewal_date")
    @classmethod
    def valid_date(cls, value):
        return validate_date(value)


class ObligationInput(Inputs):
    contract_id: Annotated[int, Field(gt=0)]
    title: NonEmpty
    description: str
    due_date: str
    owner: NonEmpty
    source_clause: str | None = None

    @field_validator("due_date")
    @classmethod
    def valid_date(cls, value):
        return validate_date(value)


class PatchInput(Inputs):
    @model_validator(mode="after")
    def validate_patch(self):
        if not self.model_fields_set:
            raise ValueError("At least one field is required")
        return self


class ContractPatch(PatchInput):
    vendor_name: NonEmpty | None = None
    title: NonEmpty | None = None
    renewal_date: str | None = None
    notice_period_days: Annotated[int, Field(ge=0)] | None = None

    @field_validator("vendor_name", "title")
    @classmethod
    def required_strings(cls, value):
        if value is None:
            raise ValueError("Field cannot be null")
        return value

    @field_validator("renewal_date")
    @classmethod
    def valid_date(cls, value):
        return validate_date(value) if value is not None else None


class ObligationPatch(PatchInput):
    title: NonEmpty | None = None
    description: Annotated[str, Field(max_length=20000)] | None = None
    owner: NonEmpty | None = None
    due_date: str | None = None
    source_clause: Annotated[str, Field(max_length=20000)] | None = None
    review_status: Literal["pending_review", "approved"] | None = None

    @field_validator("title", "review_status")
    @classmethod
    def required_fields(cls, value):
        if value is None:
            raise ValueError("Field cannot be null")
        return value

    @field_validator("due_date")
    @classmethod
    def valid_date(cls, value):
        return validate_date(value) if value is not None else None


def validate_date(value: str) -> str:
    try:
        parsed = date.fromisoformat(value)
        if parsed.isoformat() != value:
            raise ValueError()
    except ValueError:
        raise ValueError("Date must be a valid YYYY-MM-DD date") from None
    return value


def contract_data(contract: Contract) -> dict:
    return {"id": contract.id, "vendor_name": contract.vendor_name, "title": contract.title,
            "renewal_date": contract.renewal_date.isoformat() if contract.renewal_date else None,
            "notice_period_days": contract.notice_period_days, "source_clause": contract.source_clause}


def obligation_data(obligation: Obligation) -> dict:
    return {"id": obligation.id, "contract_id": obligation.contract_id, "title": obligation.title,
            "description": obligation.description, "due_date": obligation.due_date.isoformat() if obligation.due_date else None,
            "owner": obligation.owner, "source_clause": obligation.source_clause,
            "review_status": obligation.review_status, "is_completed": obligation.is_completed}


def create_contract(data: ContractInput, workspace_id: str | None = None) -> dict:
    with SessionLocal() as session:
        contract = Contract(**{**data.model_dump(), "renewal_date": date.fromisoformat(data.renewal_date)}, workspace_id=workspace_id)
        session.add(contract)
        session.commit()
        session.refresh(contract)
        return contract_data(contract)


def add_obligation(data: ObligationInput, workspace_id: str | None = None) -> dict:
    with SessionLocal() as session:
        if session.scalar(select(Contract.id).where(Contract.id == data.contract_id, Contract.workspace_id == workspace_id)) is None:
            raise ValueError("Contract not found")
        obligation = Obligation(**{**data.model_dump(), "due_date": date.fromisoformat(data.due_date)},
                                review_status="pending_review")
        session.add(obligation)
        session.commit()
        session.refresh(obligation)
        return obligation_data(obligation)


def list_contracts(workspace_id: str | None = None) -> list[dict]:
    with SessionLocal() as session:
        return [contract_data(c) for c in session.scalars(select(Contract).where(Contract.workspace_id == workspace_id).order_by(Contract.id))]


def list_obligations(contract_id: int, workspace_id: str | None = None) -> list[dict]:
    if type(contract_id) is not int or contract_id <= 0:
        raise ValueError("contract_id must be a positive integer")
    with SessionLocal() as session:
        if session.scalar(select(Contract.id).where(Contract.id == contract_id, Contract.workspace_id == workspace_id)) is None:
            raise ValueError("Contract not found")
        return [obligation_data(o) for o in session.scalars(
            select(Obligation).where(Obligation.contract_id == contract_id).order_by(Obligation.id))]


class NotFoundError(Exception):
    pass


class ConflictError(Exception):
    pass


def get_record(session, model, record_id, workspace_id):
    query = select(model).where(model.id == record_id)
    if model is Contract:
        query = query.where(Contract.workspace_id == workspace_id)
    else:
        query = query.join(Contract, Obligation.contract_id == Contract.id).where(Contract.workspace_id == workspace_id)
    record = session.scalar(query)
    if record is None:
        raise NotFoundError()
    return record


def get_contract(contract_id: int, workspace_id: str | None = None) -> dict:
    with SessionLocal() as session:
        return contract_data(get_record(session, Contract, contract_id, workspace_id))


def update_contract(contract_id: int, patch: ContractPatch, workspace_id: str | None = None) -> dict:
    with SessionLocal() as session:
        contract = get_record(session, Contract, contract_id, workspace_id)
        for field, value in patch.model_dump(exclude_unset=True).items():
            if field == "renewal_date" and value is not None:
                value = date.fromisoformat(value)
            setattr(contract, field, value)
        session.commit()
        session.refresh(contract)
        return contract_data(contract)


def rest_obligation_data(obligation: Obligation, today: date) -> dict:
    return {**obligation_data(obligation), "status": deadline_status(
        obligation.is_completed, obligation.review_status, obligation.due_date, today)}


def get_obligation(obligation_id: int, workspace_id: str | None = None) -> dict:
    with SessionLocal() as session:
        return rest_obligation_data(get_record(session, Obligation, obligation_id, workspace_id), workspace_today())


def get_obligations(contract_id: int | None = None, workspace_id: str | None = None) -> list[dict]:
    today = workspace_today()
    with SessionLocal() as session:
        query = select(Obligation).join(Contract, Obligation.contract_id == Contract.id).where(Contract.workspace_id == workspace_id).order_by(Obligation.id)
        if contract_id is not None:
            get_record(session, Contract, contract_id, workspace_id)
            query = query.where(Obligation.contract_id == contract_id)
        return [rest_obligation_data(item, today) for item in session.scalars(query)]


def update_obligation(obligation_id: int, patch: ObligationPatch, workspace_id: str | None = None) -> dict:
    with SessionLocal() as session:
        obligation = get_record(session, Obligation, obligation_id, workspace_id)
        for field, value in patch.model_dump(exclude_unset=True).items():
            if field == "due_date" and value is not None:
                value = date.fromisoformat(value)
            setattr(obligation, field, value)
        session.commit()
        session.refresh(obligation)
        return rest_obligation_data(obligation, workspace_today())


def complete_obligation(obligation_id: int, workspace_id: str | None = None) -> dict:
    with SessionLocal() as session:
        obligation = get_record(session, Obligation, obligation_id, workspace_id)
        if obligation.review_status != "approved":
            raise ConflictError("Approve the obligation before completing it")
        obligation.is_completed = True
        session.commit()
        session.refresh(obligation)
        return rest_obligation_data(obligation, workspace_today())


def dashboard_summary(workspace_id: str | None = None) -> dict:
    today = workspace_today()
    with SessionLocal() as session:
        contracts = len(session.scalars(select(Contract.id).where(Contract.workspace_id == workspace_id)).all())
        obligations = session.scalars(select(Obligation).join(Contract).where(Contract.workspace_id == workspace_id)).all()
        counts = {key: 0 for key in ("pending_review", "overdue", "due_today", "due_soon", "completed")}
        for item in obligations:
            status = deadline_status(item.is_completed, item.review_status, item.due_date, today)
            if status in counts:
                counts[status] += 1
        return {"total_contracts": contracts, "total_obligations": len(obligations),
                **{f"{key}_count": value for key, value in counts.items()}}


def dashboard_upcoming(workspace_id: str | None = None) -> list[dict]:
    today = workspace_today()
    with SessionLocal() as session:
        query = (select(Obligation).join(Contract).where(Contract.workspace_id == workspace_id, Obligation.review_status == "approved",
                 Obligation.is_completed.is_(False), Obligation.due_date.is_not(None))
                 .order_by(Obligation.due_date, Obligation.id).limit(10))
        return [rest_obligation_data(item, today) for item in session.scalars(query)]
