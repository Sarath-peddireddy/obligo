# Production deployment and Claude connection

The frontend is deployed at `https://obligo-workspace.vercel.app`; the backend and MCP endpoint are at `https://obligo-workspace-api.vercel.app` and `https://obligo-workspace-api.vercel.app/mcp`. Guest workspaces are isolated and expire after 48 hours; the existing master token grants access to the original workspace. Review provider plans before incurring charges.

## Prepare hosting

1. Provision managed PostgreSQL and a persistent Python web service. The included `render.yaml` is a Render-compatible web service configuration; it does not provision a database or select a plan. Configure `DATABASE_URL` with the provider's database URL. `postgres://`, `postgresql://`, and `postgresql+psycopg://` URLs are supported. Configure database TLS per your provider. Production rejects SQLite. The additive startup migration serializes PostgreSQL initialization and preserves existing rows; back up data before upgrading. SQLite remains the local default.
2. Set these backend environment variables in the provider's secret configuration, not in source control:
   - `OBLIGO_ENV=production`
   - `DATABASE_URL`: the managed PostgreSQL URL, including credentials as needed.
   - `MCP_BEARER_TOKEN`: at least 32 random characters. Rotate it if exposed; rotation invalidates existing browser sessions.
   - `CORS_ORIGINS`: comma-separated exact HTTPS frontend origins, without paths or wildcards.
   - `MCP_ALLOWED_HOSTS`: comma-separated exact public backend Host header values, without wildcards. Include the hostname seen by the backend through its proxy.
   - `MCP_ALLOWED_ORIGINS`: comma-separated exact HTTPS origins permitted for browser MCP clients, or an empty value if none. Non-browser Claude requests may omit Origin.
   - `WORKSPACE_TIMEZONE`: an IANA timezone, such as `UTC`.
   - `PUBLIC_MCP_URL`: the actual public HTTPS URL ending in `/mcp`, once deployed. Leave it empty until then.
   - `SEED_DEMO_WORKSPACE=true` enables fictional, individually labeled sample records for each newly created guest workspace. Existing workspaces are not changed; local development defaults to false.
3. Vercel deploys the `backend/app/main.py` FastAPI entrypoint. For local hosting, start from `backend` with `uvicorn app.main:app --host 0.0.0.0 --port $PORT`. The Render configuration uses `/health` for health checks. MCP uses stateless Streamable HTTP; browser sessions are database-backed. Ensure proxies do not log authentication headers.
4. Create a Vercel project rooted at `frontend`, with `npm run build` and output directory `dist`. Set `BACKEND_ORIGIN` locally to the actual HTTPS backend origin, then run `node scripts/configure-vercel.mjs` from `frontend`; it inserts an `/api/*` rewrite into `vercel.json`. Review and upload it as part of your deployment. The script refuses to replace an existing API rewrite. Leave `VITE_API_URL` and `VITE_FRONTEND_ONLY` blank, so browsers use the frontend origin and its secure SameSite cookie. Put that exact frontend origin in backend `CORS_ORIGINS`.
5. Verify the public frontend, backend `/health`, authenticated MCP discovery and writes, and frontend editing against a dedicated test workspace after changes. The current deployment passed these checks; Claude.ai itself has not been tested.

## Connect Claude.ai

Claude's custom connector runs from Anthropic's cloud and cannot reach localhost. Once the public backend is deployed and verified:

1. Open **Claude.ai → Customize → Connectors → Add → Custom → Web**.
2. Enter a connector name and the MCP URL `https://obligo-workspace-api.vercel.app/mcp`.
3. In Obligo, use **Connect Claude** to create a guest-specific authorization header. Under **Request headers** in Claude, add the header name `Authorization` and paste that value. Store it only in Claude's credential settings; do not include it in code or prompts. Select no OAuth sign-in if the flow offers that option. The guest credential expires with the workspace and is revoked at sign-out.
4. Finish adding the connector. Enable tools if Claude offers per-tool controls, and verify discovery of `create_contract`, `add_obligation`, `list_contracts`, and `list_obligations`.
5. Example prompt: “Using Obligo, create a contract for Example Vendor titled Services Agreement, renewing 2028-04-01 with a 30-day notice period; then add an obligation to send renewal notice by 2028-03-02, owned by Legal.” Review extracted obligations against their source clauses before approval.

See [Claude's custom connector instructions](https://support.claude.com/en/articles/11176164-use-connectors-to-extend-claude-s-capabilities). Claude connectivity has not yet been tested.
