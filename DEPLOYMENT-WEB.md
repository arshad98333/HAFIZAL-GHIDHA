# Web stack deployment (API + UI)

Deploy the FastAPI backend to **Azure Container Apps** (scale-to-zero) and the React dashboard to **Azure Static Web Apps**.

## Prerequisites

- `az login` (same subscription as your OpenAI / MongoDB setup)
- Docker (build API image)
- Node.js 20+ (build frontend)
- `.env` with `MONGODB_URI`, `AZURE_OPENAI_ENDPOINT`, `FOUNDRY_*`, `TRAINING_REGION`

## One command (Windows)

```powershell
cd C:\Users\HI\Desktop\HAFIZAL-GHIDHA
git pull origin main
az login
gh auth token | docker login ghcr.io -u YOUR_GITHUB_USER --password-stdin
.\scripts\deploy-azure-web.ps1
```

On success you get:

- `API: https://<fqdn>` — FastAPI + `/simulate` + `/docs`
- `UI: https://<swa-host>` — React app with `VITE_API_BASE_URL` pointing at the API
- `Simulation: https://<swa-host>/simulation`

## First deploy vs update

| Flag | When |
|------|------|
| (default) | First deploy: provisions resource group, Container App, Static Web App |
| `-SkipInfra` | Update only: new API image + frontend redeploy |
| `-SkipApiImage` | Frontend-only redeploy |
| `-SkipFrontend` | API image + Container App only |

## GitHub Actions

1. Add repository **secrets**: `MONGODB_URI`, `AZURE_STATIC_WEB_APPS_API_TOKEN`
2. Add **variables**: `AZURE_CLIENT_ID`, `AZURE_TENANT_ID`, `AZURE_SUBSCRIPTION_ID`, `AZURE_RESOURCE_GROUP`, `AZURE_API_APP_NAME`, `AZURE_STATIC_WEB_APP_NAME`, `AZURE_OPENAI_ENDPOINT`, `FOUNDRY_*`, `TRAINING_REGION`
3. Actions → **Deploy Web + API** → Run workflow → check **provision** on first run

The workflow builds the frontend with the live API FQDN after updating the Container App.

## Verify

```powershell
curl https://<api-fqdn>/health
curl -X POST https://<api-fqdn>/simulate -H "Content-Type: application/json" -d "{\"product\":\"finfish_seafood\",\"fault_mode\":\"in_spec\",\"jurisdiction\":\"AE\",\"artifact_type\":\"logger_csv\",\"seed\":1}"
```

Open `https://<swa-host>/simulation` and run a scenario — the chart and disposition should update without local API.

## Troubleshooting

| Issue | Fix |
|-------|-----|
| API docs blank at `/api/docs` locally | Use http://127.0.0.1:8080/docs or set `VITE_API_DIRECT_URL` |
| UI cannot reach API in Azure | Rebuild frontend with correct `VITE_API_BASE_URL` (deploy script does this) |
| Container App won't start | Check `az containerapp logs show` — usually missing `MONGODB_URI` secret |
| GHCR pull denied | Make package public or add registry credentials to Container App |
