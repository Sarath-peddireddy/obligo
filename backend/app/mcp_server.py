"""MCP protocol adapters; persistence belongs to the shared service layer."""
from typing import Annotated
import logging

from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from pydantic import BaseModel, Field

from app import services
from app.config import settings
from app.workspace_context import workspace_context

mcp = FastMCP("Obligo", json_response=True, stateless_http=True, log_level="WARNING", transport_security=TransportSecuritySettings(
    enable_dns_rebinding_protection=True, allowed_hosts=settings.allowed_mcp_hosts,
    allowed_origins=settings.allowed_mcp_origins))
# The SDK transport loggers include session identifiers in lifecycle messages.
for logger_name in ("mcp.server.streamable_http", "mcp.server.streamable_http_manager"):
    logging.getLogger(logger_name).disabled = True


class ContractResult(BaseModel):
    id: int
    vendor_name: str
    title: str
    renewal_date: str | None
    notice_period_days: int | None
    source_clause: str | None


class ObligationResult(BaseModel):
    id: int
    contract_id: int
    title: str
    description: str | None
    due_date: str | None
    owner: str | None
    source_clause: str | None
    review_status: str
    is_completed: bool


@mcp.tool()
def create_contract(vendor_name: str, title: str, renewal_date: str,
                    notice_period_days: Annotated[int, Field(strict=True)], source_clause: str | None = None) -> ContractResult:
    """Save a contract in the demo workspace. Dates use YYYY-MM-DD."""
    return ContractResult(**services.create_contract(services.ContractInput(
        vendor_name=vendor_name, title=title, renewal_date=renewal_date,
        notice_period_days=notice_period_days, source_clause=source_clause), workspace_context.get()))


@mcp.tool()
def add_obligation(contract_id: Annotated[int, Field(strict=True)], title: str, description: str,
                   due_date: str, owner: str, source_clause: str | None = None) -> ObligationResult:
    """Save an obligation for an existing contract. Dates use YYYY-MM-DD."""
    return ObligationResult(**services.add_obligation(services.ObligationInput(
        contract_id=contract_id, title=title, description=description, due_date=due_date,
        owner=owner, source_clause=source_clause), workspace_context.get()))


@mcp.tool()
def list_contracts() -> list[ContractResult]:
    """List contracts in the demo workspace."""
    return [ContractResult(**item) for item in services.list_contracts(workspace_context.get())]


@mcp.tool()
def list_obligations(contract_id: Annotated[int, Field(strict=True, gt=0)]) -> list[ObligationResult]:
    """List obligations belonging to a contract."""
    return [ObligationResult(**item) for item in services.list_obligations(contract_id, workspace_context.get())]
