<div align="center">

# Obligo

### From contractual commitments to accountable execution.

**A contract obligation workspace powered by your Claude account through MCP.**

[**Live demo**](https://obligo-workspace.vercel.app) · [**MCP endpoint**](https://obligo-workspace-api.vercel.app/mcp)

</div>

---

## The problem

A signed contract is not the end of the work. It can contain renewal windows, notice periods, approvals, and responsibilities that someone needs to act on months later.

Those commitments often remain buried in documents or scattered across calendars and spreadsheets. Reading a contract is a one-time task; **following through is an ongoing operational responsibility**.

## The product

**Obligo turns contract terms into trackable obligations.**

A user reviews an agreement with Claude and asks it to create a contract in Obligo. Through the Model Context Protocol (MCP), Claude sends structured records into the workspace. The team can then verify the extracted terms, correct owners and dates, and track what is due — without keeping Claude open.

| Claude handles | Obligo handles |
| --- | --- |
| Reading and interpreting the agreement | Persisting contracts and obligations |
| Identifying possible deadlines and actions | Human review and edits |
| Structuring information for MCP tools | Deadline status and completion tracking |

**No model inference runs inside Obligo.** The user brings their own Claude access; the application provides the persistent workflow.

## How it works

```text
Agreement → Claude → Obligo MCP tools → Database → Workspace
                                                 ↓
                                Review → Assign → Track → Complete
```

1. **Connect Claude.** Open Obligo as a guest and follow the in-app **Connect Claude** guide.
2. **Create a contract.** Give Claude a vendor agreement and ask it to save the relevant terms using Obligo's MCP tools.
3. **Verify the extraction.** Review source clauses, owners, and deadlines before approving obligations.
4. **Manage the work.** Edit records, monitor upcoming or overdue obligations, and mark actions complete in Obligo.

> **Product principle:** Claude helps interpret the contract. Obligo makes the work visible and accountable after the conversation ends.

## Built for the operational handoff

- **Contract register** — vendor agreements, renewal dates, and notice periods in one place.
- **Obligation tracking** — actionable items tied to their source contract.
- **Human-in-the-loop review** — AI-extracted terms remain pending review until approved.
- **Deadline visibility** — due-soon, due-today, overdue, and completed states.
- **Guest demo workspaces** — isolated sessions and workspace-specific MCP credentials.
- **Editable records** — changes persist independently of the Claude conversation.

## Architecture

| Layer | Implementation |
| --- | --- |
| Frontend | React · TypeScript · Vite |
| API | FastAPI · Python |
| AI-to-app interface | Model Context Protocol (MCP), Streamable HTTP |
| Persistence | PostgreSQL (Neon); SQLite for local development |
| Deployment | Vercel |
| Icons and interface | Lucide · minimalist operational UI |

Obligo exposes four MCP tools: `create_contract`, `add_obligation`, `list_contracts`, and `list_obligations`. These use the same persistent business records as the web application.

## Try Obligo

**[Open the live demo](https://obligo-workspace.vercel.app)**

1. Select **Continue as Guest**.
2. Click **Connect Claude** and follow the guided connector setup.
3. Use a fictional sample vendor agreement in Claude to create a contract and obligations.
4. Return to Obligo to review, edit, and track them.

**Remote MCP URL:** `https://obligo-workspace-api.vercel.app/mcp`

A guest-specific authorization credential is required. Obtain it inside the application; do not use a shared token or publish credentials in a repository.

## Run locally

Requirements: Python 3.13, Node.js and npm. From the project root, start the backend in PowerShell:

```powershell
cd backend
py -3.13 -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements.txt
Copy-Item .env.example .env
.\.venv\Scripts\python -m uvicorn app.main:app --reload
```

In a second terminal, start the frontend:

```powershell
cd frontend
npm ci
npm run dev
```

Open `http://localhost:5173` and continue as a guest. Local development uses SQLite. Set a long random `MCP_BEARER_TOKEN` in `backend/.env` for master-token access; never commit that file. The local MCP endpoint is `http://127.0.0.1:8000/mcp`; the in-app remote connector guide requires a publicly reachable HTTPS endpoint.

Run checks with `npm run build` and `npm run test:ui` from `frontend`, and `.\.venv\Scripts\python -m unittest discover -s tests -v` from `backend`. The browser test uses Chrome on Windows by default; set `CHROME_PATH` if needed.

## Product scope & limitations

Obligo is a **working assignment MVP**, not a legal-advice service or a production-ready enterprise contract lifecycle management suite. Contract interpretation can be incomplete or incorrect; people must verify source clauses and dates before relying on them. Guest access is intended for testing with fictional, non-confidential agreements, and demo workspaces expire.

The initial product hypothesis is straightforward: teams may pay to reduce missed contractual actions and make ownership explicit. **Willingness to pay and measurable business impact have not yet been validated.**

---

<div align="center">

**Obligo** · Contracts shouldn't become forgotten commitments.

</div>
