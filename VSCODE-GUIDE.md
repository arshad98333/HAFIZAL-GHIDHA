# Running this project in VS Code

## One-time setup

1. Open the folder in VS Code: `File -> Open Folder... -> C:\Users\HI\Desktop\HAFIZAL-GHIDHA-main`
2. Install prerequisites if you don't already have them:
   - Python 3.11 or 3.12
   - Node.js 20+
   - Git (already working, since you can push)
3. Make sure `.env` exists in the repo root with real values for `MONGODB_URI`,
   `K2_API_KEY`, `K2_BASE_URL`, etc. (copy `.env.example` if you don't have one yet).
   VS Code should show it in the file explorer even though it's git-ignored.
4. If VS Code asks about the PowerShell execution policy the first time you run a
   script, run this once in a terminal (as your normal user, not admin):
   ```powershell
   Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
   ```

## Every day: run backend + frontend together

Open two integrated terminals in VS Code (`` Ctrl+` `` then click the `+` to split,
or `Terminal -> New Terminal` twice). Both default to PowerShell.

**Terminal 1 - backend:**
```powershell
.\run-backend.ps1
```
This pulls the latest `main`, creates/updates the virtualenv, installs
`requirements.txt`, and starts the API on `http://127.0.0.1:8080` with
auto-reload. Leave it running.

**Terminal 2 - frontend:**
```powershell
.\run-frontend.ps1
```
This pulls latest `main`, runs `npm install`, and starts the Vite dev server on
`http://127.0.0.1:5173`. Leave it running too.

Open **http://127.0.0.1:5173** in your browser. The dashboard talks to the
backend on port 8080 automatically in dev mode.

Useful flags on both scripts:
- `-NoPull` - skip the `git pull` step (e.g. you have local uncommitted changes
  you don't want to risk conflicting with a pull)
- `-NoInstall` - skip `pip install` / `npm install` (faster restart once
  dependencies are already installed)
- `-Port <n>` - use a different port

## Publishing your changes (GitHub + Azure)

When you're happy with a change and want it pushed to GitHub and deployed:

```powershell
.\deploy.ps1
```

This will:
1. `git add -A`, commit (auto-generated message, or pass `-Message "..."`),
   and `git push` to `origin main` (fast-forwards on top of `origin/main`
   first if you're behind - never force-pushes).
2. Rebuild and redeploy the API container + frontend to Azure, provided
   `az login` has already been run in that terminal and the Azure CLI is
   installed.

Flags: `-SkipGitHub` (Azure only), `-SkipAzure` (GitHub only),
`-SkipApiImage` (redeploy infra/frontend without rebuilding the API image -
faster when only the frontend changed).

Pushing to `main` also kicks off the GitHub Actions CI pipeline
(`.github/workflows/ci.yml`): lint/typecheck/tests, an integration test
against a throwaway Mongo container, a dependency vulnerability audit
(`pip-audit`), a Docker build, and a frontend build. Check the **Actions**
tab on GitHub after pushing to confirm it's green.

## If something looks broken

- **Backend won't start / import errors** - re-run `.\run-backend.ps1` without
  `-NoInstall` so it reinstalls `requirements.txt`.
- **"K2 is not configured" (503) on the Ask page** - `K2_API_KEY` is missing
  from `.env`.
- **CI red on GitHub Actions** - run the same checks locally before pushing:
  ```powershell
  python -m pip install -r requirements-dev.txt
  make check PYTHON=python
  python -m pip install pip-audit
  python -m pip_audit -r requirements.txt --strict
  ```
- **Live Azure Ask page shows a bare "HTTP 500" with no message** - this was
  traced to the API container being scaled to zero replicas (cold start) and
  to `K2_API_KEY`/`K2_BASE_URL` never being deployed to Azure; both are fixed
  in `infra/web-stack.json` and `scripts/deploy-azure-web.ps1` - redeploy with
  `.\deploy.ps1` to pick up the fix.
