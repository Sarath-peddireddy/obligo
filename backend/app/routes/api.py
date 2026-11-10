from typing import Annotated

from fastapi import APIRouter, Depends, Path

from app import services
from app.auth import require_session

router = APIRouter(prefix="/api", dependencies=[Depends(require_session)])
ID = Annotated[int, Path(gt=0)]


@router.get("/contracts")
def contracts(workspace: str | None = Depends(require_session)):
    return services.list_contracts(workspace)


@router.get("/contracts/{contract_id}")
def contract(contract_id: ID, workspace: str | None = Depends(require_session)):
    return services.get_contract(contract_id, workspace)


@router.patch("/contracts/{contract_id}")
def patch_contract(contract_id: ID, patch: services.ContractPatch, workspace: str | None = Depends(require_session)):
    return services.update_contract(contract_id, patch, workspace)


@router.get("/contracts/{contract_id}/obligations")
def contract_obligations(contract_id: ID, workspace: str | None = Depends(require_session)):
    return services.get_obligations(contract_id, workspace)


@router.get("/obligations")
def obligations(workspace: str | None = Depends(require_session)):
    return services.get_obligations(workspace_id=workspace)


@router.get("/obligations/{obligation_id}")
def obligation(obligation_id: ID, workspace: str | None = Depends(require_session)):
    return services.get_obligation(obligation_id, workspace)


@router.patch("/obligations/{obligation_id}")
def patch_obligation(obligation_id: ID, patch: services.ObligationPatch, workspace: str | None = Depends(require_session)):
    return services.update_obligation(obligation_id, patch, workspace)


@router.post("/obligations/{obligation_id}/complete")
def complete_obligation(obligation_id: ID, workspace: str | None = Depends(require_session)):
    return services.complete_obligation(obligation_id, workspace)


@router.get("/dashboard/summary")
def dashboard_summary(workspace: str | None = Depends(require_session)):
    return services.dashboard_summary(workspace)


@router.get("/dashboard/upcoming")
def dashboard_upcoming(workspace: str | None = Depends(require_session)):
    return services.dashboard_upcoming(workspace)
