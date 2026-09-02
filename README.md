# GCC Cold-Chain Compliance AI

[![License: MIT](https://img.shields.io/badge/license-MIT-3C3489)](LICENSE)
[![Python 3.11 | 3.12](https://img.shields.io/badge/python-3.11%20%7C%203.12-0C447C)](requirements.txt)
[![React UI](https://img.shields.io/badge/UI-React%20%2B%20Tailwind-0C447C)](frontend/)

GSO-aligned cold-chain compliance AI for **Saudi Arabia, UAE, Qatar, Bahrain, Kuwait, and Oman**. Inspect temperature logs, QC forms, chat messages, and voice notes with a deterministic rules engine — every training label is law-grounded, never LLM-generated.

**Web dashboard:** bilingual English / Arabic · **API:** FastAPI · **Pipeline:** one command per goal

---

## Live deployment (Azure)

Production stack on Azure Container Apps (API, scale-to-zero) + Azure Static Web Apps (UI).

| Service | Base URL |
|---------|----------|
| **Web UI** | https://lively-river-053b63203.3.azurestaticapps.net |
| **API** | https://gcc-coldchain-api.grayfield-8c57c3df.uaenorth.azurecontainerapps.io |
| **OpenAPI / Swagger** | https://gcc-coldchain-api.grayfield-8c57c3df.uaenorth.azurecontainerapps.io/docs |
| **ReDoc** | https://gcc-coldchain-api.grayfield-8c57c3df.uaenorth.azurecontainerapps.io/redoc |

### Live UI pages

| Page | URL |
|------|-----|
| Landing | https://lively-river-053b63203.3.azurestaticapps.net/ |
| Simulation | https://lively-river-053b63203.3.azurestaticapps.net/simulation |
| Dashboard | https://lively-river-053b63203.3.azurestaticapps.net/dashboard |
| Pipeline | https://lively-river-053b63203.3.azurestaticapps.net/pipeline |
| Setup guide | https://lively-river-053b63203.3.azurestaticapps.net/guide |
| Jobs | https://lively-river-053b63203.3.azurestaticapps.net/jobs |

The UI calls the API directly (CORS enabled). `VITE_API_BASE_URL` was set at deploy time to the API base URL above.

### Live API — meta & health

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | https://gcc-coldchain-api.grayfield-8c57c3df.uaenorth.azurecontainerapps.io/ | Service metadata |
| GET | https://gcc-coldchain-api.grayfield-8c57c3df.uaenorth.azurecontainerapps.io/health | Config liveness |
| GET | https://gcc-coldchain-api.grayfield-8c57c3df.uaenorth.azurecontainerapps.io/ready | MongoDB readiness |

### Live API — simulation

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | https://gcc-coldchain-api.grayfield-8c57c3df.uaenorth.azurecontainerapps.io/simulate | Deterministic demo: synthesize temps, rules-engine label, artifact preview (no LLM) |

```powershell
curl -X POST "https://gcc-coldchain-api.grayfield-8c57c3df.uaenorth.azurecontainerapps.io/simulate" `
  -H "Content-Type: application/json" `
  -d '{"product":"finfish_seafood","fault_mode":"door_open","jurisdiction":"AE","artifact_type":"logger_csv","seed":42}'
```

### Live API — waves (read)

Replace `{n}` with wave number (e.g. `1`).

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `.../waves/{n}/audit` | Wave summary (rows, kept, Gate A status) |
| GET | `.../waves/{n}/plan` | Read `plan.json` |
| GET | `.../waves/{n}/gate-a` | Read Gate A report |
| GET | `.../waves/{n}/gate-b` | Read Gate B report |
| GET | `.../waves/{n}/preflight` | Read preflight report |
| GET | `.../waves/{n}/decisions` | Decision log |
| GET | `.../waves/{n}/records` | Paginated generation log (`?limit=20&offset=0`) |
| GET | `.../waves/{n}/records/count` | Outcome counts |
| GET | `.../waves/{n}/kpi` | 12-KPI scorecard |

Example: https://gcc-coldchain-api.grayfield-8c57c3df.uaenorth.azurecontainerapps.io/waves/1/audit

### Live API — pipeline (write, background jobs)

POST returns `202 Accepted` with a `job_id`. Poll `/jobs/{id}` until `status` is `succeeded` or `failed`.

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `.../waves/{n}/plan` | Run wave planning |
| POST | `.../waves/{n}/generate` | Run corpus generation |
| POST | `.../waves/{n}/gate-a` | Run Gate A evaluation |
| POST | `.../waves/{n}/preflight` | Run preflight check |
| POST | `.../waves/{n}/train` | Run training submit |
| POST | `.../waves/{n}/gate-b` | Run Gate B evaluation |

Example: `POST https://gcc-coldchain-api.grayfield-8c57c3df.uaenorth.azurecontainerapps.io/waves/1/gate-a`

### Live API — jobs

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | https://gcc-coldchain-api.grayfield-8c57c3df.uaenorth.azurecontainerapps.io/jobs | List jobs (`?wave=1` optional) |
| GET | https://gcc-coldchain-api.grayfield-8c57c3df.uaenorth.azurecontainerapps.io/jobs/{id} | Job status and result |

### Live API — data

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | https://gcc-coldchain-api.grayfield-8c57c3df.uaenorth.azurecontainerapps.io/ledger | Training ledger |
| GET | https://gcc-coldchain-api.grayfield-8c57c3df.uaenorth.azurecontainerapps.io/coverage | Coverage matrix |

> **Note:** `...` = `https://gcc-coldchain-api.grayfield-8c57c3df.uaenorth.azurecontainerapps.io`  
> Jobs are in-memory on the API container; they reset when the app scales to zero or restarts.

---

## One command per goal

| Goal | Windows (PowerShell) | Linux / macOS |
|------|----------------------|---------------|
| **Setup** (venv + deps) | `python -m venv venv; .\venv\Scripts\Activate.ps1; pip install -r requirements-dev.txt` | `make install` |
| **Re-score** existing data | `.\scripts\run.ps1` | `make run` |
| **Smoke test** (10 records) | `.\scripts\run.ps1 -Profile smoke` | `make run-smoke` |
| **Full wave** (~663 records) | `.\scripts\run.ps1 -Profile wave` | `make run-wave` |
| **Start API** | `.\scripts\api_server.ps1` | `make api` |
| **Start web UI** | `.\scripts\ui.ps1` | `make ui` |
| **Try simulation** | Open http://127.0.0.1:5173/simulation | same |
| **Deploy to Azure** | `.\scripts\deploy-azure-web.ps1` | see DEPLOYMENT-WEB.md |
| **Update all** (git + deps + sync) | `.\scripts\update-all.ps1` | `make update-all` |
| **Update + deploy Azure** | `.\scripts\update-all.ps1 -Deploy` | `make update-all DEPLOY=1` |
| **Sync to `-main` folder** | `.\scripts\watch-sync-desktop.ps1` | `./scripts/sync-desktop-folder.ps1` |
| **Health check** | `python -m cold_chain.runner health` | `make health` |

Open **http://127.0.0.1:5173** (UI) · **http://127.0.0.1:8080/docs** (API)

---

## First-time setup (one block)

```powershell
# Windows
git clone https://github.com/arshad98333/HAFIZAL-GHIDHA.git
cd HAFIZAL-GHIDHA
git checkout main
python -m venv venv
.\venv\Scripts\Activate.ps1
pip install -r requirements-dev.txt
copy .env.example .env   # fill MONGODB_URI, AZURE_OPENAI_ENDPOINT, etc.
az login
.\scripts\run.ps1 -Profile smoke
```

```bash
# Linux / macOS
git clone https://github.com/arshad98333/HAFIZAL-GHIDHA.git && cd HAFIZAL-GHIDHA
make install
cp .env.example .env
az login
make run-smoke
```

---

## Web UI + API (local)

**Terminal 1 — API:**
```powershell
.\scripts\api_server.ps1          # Windows
make api                            # Linux/macOS
```

**Terminal 2 — React dashboard:**
```powershell
.\scripts\ui.ps1                    # Windows
make ui                             # Linux/macOS
```

The UI proxies `/api` → `http://127.0.0.1:8080`. Configure via `frontend/.env`:

```
VITE_API_BASE_URL=/api
VITE_API_PROXY_TARGET=http://127.0.0.1:8080
```

### UI pages

| Page | URL | Purpose |
|------|-----|---------|
| Landing | `/` | GSO business value, SEO |
| **Simulation** | `/simulation` | Interactive demo: inputs → temps → rules engine |
| Dashboard | `/dashboard` | Wave audit, Gate A, health |
| Pipeline | `/pipeline` | Trigger plan / generate / gate-a |
| Guide | `/guide` | Copy-paste single commands |
| Jobs | `/jobs` | Background job status |

Toggle **EN / عربي** in the header (RTL layout for Arabic).

---

## API endpoints (local)

For local development, base URL is **http://127.0.0.1:8080**. See [Live deployment](#live-deployment-azure) for production URLs.

| Method | Path | Description |
|--------|------|-------------|
| GET | `/` | Service metadata |
| GET | `/health` | Config liveness |
| GET | `/ready` | MongoDB ping |
| POST | `/simulate` | Deterministic demo (no Mongo/LLM) |
| GET | `/waves/{n}/audit` | Wave summary |
| GET | `/waves/{n}/plan` | Read plan |
| GET | `/waves/{n}/gate-a` | Read Gate A report |
| GET | `/waves/{n}/gate-b` | Read Gate B report |
| GET | `/waves/{n}/preflight` | Read preflight |
| GET | `/waves/{n}/decisions` | Decision log |
| GET | `/waves/{n}/records` | Paginated records |
| GET | `/waves/{n}/records/count` | Outcome counts |
| GET | `/waves/{n}/kpi` | 12 KPI scorecard |
| POST | `/waves/{n}/plan` | Run plan (background job) |
| POST | `/waves/{n}/generate` | Run generate |
| POST | `/waves/{n}/gate-a` | Run Gate A |
| POST | `/waves/{n}/preflight` | Run preflight |
| POST | `/waves/{n}/train` | Run train |
| POST | `/waves/{n}/gate-b` | Run Gate B |
| GET | `/jobs` | List jobs |
| GET | `/jobs/{id}` | Job status |
| GET | `/ledger` | Training ledger |
| GET | `/coverage` | Coverage matrix |

Full OpenAPI: **http://127.0.0.1:8080/docs**

---

## Deploy to Azure

| Component | Azure service | Image / artifact |
|-----------|---------------|------------------|
| **API** | Container Apps (HTTP, scale-to-zero) | `Dockerfile.api` |
| **UI** | Static Web Apps | `frontend/dist` |
| **Pipeline batch** | Container Apps Job | `Dockerfile` |

**One command (Windows, after `az login`):**

```powershell
.\scripts\deploy-azure-web.ps1
```

No Docker or GitHub CLI required — builds the API image in Azure Container Registry.

**GitHub Actions:** `.github/workflows/deploy-web.yml` (manual dispatch, check **provision** on first run).

See [DEPLOYMENT-WEB.md](DEPLOYMENT-WEB.md) for details. Batch pipeline: [DEPLOYMENT.md](DEPLOYMENT.md).

---

## Troubleshooting

| Issue | Fix |
|-------|-----|
| `uvicorn` not found on Windows | `.\scripts\api_server.ps1` (uses venv python) |
| Gate A fails on rescore | Reset MongoDB: `python scripts/reset_pipeline_state.py --yes --wave 1` then `.\scripts\run.ps1 -Profile wave` |
| PowerShell parse error | `git pull origin main` (ASCII-only `.ps1` scripts) |
| UI cannot reach API | Start API first; check `frontend/.env` proxy target |

---

## Architecture

```
React UI (Static Web App)  →  FastAPI (Container Apps HTTP)
                                    ↓
                              cold_chain.runner stages
                                    ↓
                              MongoDB Atlas logbook
```

Executive summary: [`One_Engine_Six_Jurisdictions.pdf`](One_Engine_Six_Jurisdictions.pdf)

License: MIT
