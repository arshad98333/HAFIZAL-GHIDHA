# Web stack deployment (API + UI)

Deploy the FastAPI backend to **Azure Container Apps** (scale-to-zero) and the React dashboard to **Azure Static Web Apps**.

## Prerequisites

- `az login` (same subscription as your OpenAI / MongoDB setup)
- **Node.js 20+** (frontend build + SWA deploy)
- `.env` with `MONGODB_URI`, `AZURE_OPENAI_ENDPOINT`
- **No Docker required** — API image builds in Azure Container Registry

## One command (Windows)

```powershell
cd C:\Users\HI\Desktop\HAFIZAL-GHIDHA
git pull origin cursor/simulation-azure-deploy-2905
az login
.\scripts\deploy-azure-web.ps1
```

On success you get URLs like:

- **UI:** https://lively-river-053b63203.3.azurestaticapps.net
- **API:** https://gcc-coldchain-api.grayfield-8c57c3df.uaenorth.azurecontainerapps.io

Full endpoint list: [README — Live deployment](README.md#live-deployment-azure).

First run takes ~5–10 minutes (ACR cloud build + ARM deploy + npm build).

## First deploy vs update

| Flag | When |
|------|------|
| (default) | First deploy: ACR + Container App + Static Web App |
| `-SkipInfra` | Update only: new API image + frontend redeploy |
| `-SkipApiImage` | Frontend-only redeploy |
| `-SkipFrontend` | API image + Container App only |

## Build methods

| `-BuildMethod` | Needs | Use when |
|----------------|-------|----------|
| `Acr` (default) | `az` only | **Windows without Docker** |
| `Docker` | Local Docker | Not for Azure (local images can't be pulled) |
| `Ghcr` | Docker + `gh auth login` | CI / dev with Docker Desktop |

## GitHub Actions

1. Add repository **secrets**: `MONGODB_URI`, `AZURE_STATIC_WEB_APPS_API_TOKEN`
2. Add **variables**: `AZURE_CLIENT_ID`, `AZURE_TENANT_ID`, `AZURE_SUBSCRIPTION_ID`, `AZURE_RESOURCE_GROUP`, `AZURE_API_APP_NAME`, `AZURE_STATIC_WEB_APP_NAME`, `AZURE_OPENAI_ENDPOINT`, `FOUNDRY_*`, `TRAINING_REGION`
3. Actions → **Deploy Web + API** → Run workflow → check **provision** on first run

## Verify

```powershell
curl https://<api-fqdn>/health
curl -X POST https://<api-fqdn>/simulate -H "Content-Type: application/json" -d "{\"product\":\"finfish_seafood\",\"fault_mode\":\"in_spec\",\"jurisdiction\":\"AE\",\"artifact_type\":\"logger_csv\",\"seed\":1}"
```

Open `https://<swa-host>/simulation` and run a scenario.

## Troubleshooting

| Issue | Fix |
|-------|-----|
| `docker` not recognized | Use default `-BuildMethod Acr` — no Docker needed |
| `gh auth login` error | Ignore — script no longer requires GitHub CLI |
| Static Web App region error | Script uses `-StaticWebLocation westeurope` by default (SWA not in all regions) |
| API docs blank locally | Use http://127.0.0.1:8080/docs |
| Container App won't start | `az containerapp logs show -n gcc-coldchain-api -g gcc-coldchain-rg --follow` |
| `npm` not found | Install Node.js 20+ from https://nodejs.org |
