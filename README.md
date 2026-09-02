# GCC Cold-Chain Compliance AI

[![License: MIT](https://img.shields.io/badge/license-MIT-3C3489)](LICENSE)
[![Python 3.11 | 3.12](https://img.shields.io/badge/python-3.11%20%7C%203.12-0C447C)](requirements.txt)
[![React UI](https://img.shields.io/badge/UI-React%20%2B%20Tailwind-0C447C)](frontend/)

GSO-aligned cold-chain compliance AI for **Saudi Arabia, UAE, Qatar, Bahrain, Kuwait, and Oman**. Inspect temperature logs, QC forms, chat messages, and voice notes with a deterministic rules engine — every training label is law-grounded, never LLM-generated.

**Web dashboard:** bilingual English / Arabic · **API:** FastAPI · **Pipeline:** one command per goal

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
| Dashboard | `/dashboard` | Wave audit, Gate A, health |
| Pipeline | `/pipeline` | Trigger plan / generate / gate-a |
| Guide | `/guide` | Copy-paste single commands |
| Jobs | `/jobs` | Background job status |

Toggle **EN / عربي** in the header (RTL layout for Arabic).

---

## API endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/health` | Config liveness |
| GET | `/ready` | MongoDB ping |
| GET | `/waves/{n}/audit` | Wave summary |
| GET | `/waves/{n}/kpi` | 12 KPI scorecard |
| POST | `/waves/{n}/gate-a` | Run Gate A (background job) |
| GET | `/jobs/{id}` | Poll job status |

Full OpenAPI: **http://127.0.0.1:8080/docs**

---

## Deploy to Azure

| Component | Azure service | Image / artifact |
|-----------|---------------|------------------|
| **API** | Container Apps (HTTP, scale-to-zero) | `Dockerfile.api` |
| **UI** | Static Web Apps | `frontend/dist` |
| **Pipeline batch** | Container Apps Job | `Dockerfile` |

1. Provision: `infra/web-stack.json` (API + Static Web App)
2. CI/CD: `.github/workflows/deploy-web.yml` (manual dispatch)
3. Set GitHub vars: `VITE_API_BASE_URL=https://<api-fqdn>` (auto-injected at build)
4. Secrets: `AZURE_STATIC_WEB_APPS_API_TOKEN`, Azure OIDC vars

See [DEPLOYMENT.md](DEPLOYMENT.md) for the batch pipeline job.

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
