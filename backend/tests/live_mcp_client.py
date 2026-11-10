"""Live smoke helper. Reads a guest token from stdin and never logs it."""
import asyncio
import json
import sys

import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client


async def run(data):
    async with httpx.AsyncClient(headers={"Authorization": "Bearer " + data["token"]}, trust_env=False, timeout=60) as client:
        async with streamable_http_client(data["url"], http_client=client) as (read, write, get_id):
            async with ClientSession(read, write) as session:
                await session.initialize()
                assert get_id() is None
                tools = await session.list_tools()
                assert {tool.name for tool in tools.tools} == {"create_contract", "add_obligation", "list_contracts", "list_obligations"}
                contract = await session.call_tool("create_contract", {"vendor_name": data["marker"], "title": "Live test contract", "renewal_date": "2028-04-20", "notice_period_days": 30})
                assert not contract.isError
                cid = contract.structuredContent["id"]
                obligation = await session.call_tool("add_obligation", {"contract_id": cid, "title": data["marker"], "description": "Live test obligation", "due_date": "2028-03-20", "owner": "Demo"})
                assert not obligation.isError
                oid = obligation.structuredContent["id"]
    async with httpx.AsyncClient(headers={"Authorization": "Bearer " + data["token"]}, trust_env=False, timeout=60) as client:
        async with streamable_http_client(data["url"], http_client=client) as (read, write, _):
            async with ClientSession(read, write) as session:
                await session.initialize()
                assert any(item["id"] == cid for item in (await session.call_tool("list_contracts", {})).structuredContent["result"])
                assert any(item["id"] == oid for item in (await session.call_tool("list_obligations", {"contract_id": cid})).structuredContent["result"])
    print(json.dumps({"contract_id": cid, "obligation_id": oid}))


try:
    asyncio.run(run(json.load(sys.stdin)))
except Exception as error:
    print("MCP client test failed: " + type(error).__name__, file=sys.stderr)
    sys.exit(1)
