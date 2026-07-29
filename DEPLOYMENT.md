# Deploying to Azure Container Apps

This pipeline ships as an **Azure Container Apps Job**, not a web app. Every
stage (`plan`, `generate`, `gate-a`, `train`, `gate-b`) is a separate,
resumable CLI invocation (see `README.md`), which is exactly what a
manually-triggered Container Apps Job is for: run one execution, it does one
stage of one wave, and exits. There's no HTTP listener to keep warm and no
idle cost between waves.

`infra/main.json` provisions everything: a Log Analytics workspace, a
Container Apps managed environment, and the Job itself.
`.github/workflows/cd.yml` builds the image and pushes it to GitHub
Container Registry on every push to `main`; pointing the Job at that image
and running it happens separately, by manual dispatch (see below).

## One-click provisioning

Click the button in `README.md` ("Deploy to Azure"), or run:

```bash
az deployment group create \
  --resource-group <your-resource-group> \
  --template-file infra/main.json \
  --parameters containerImage=ghcr.io/arshad98333/hafizal-ghidha:latest \
               mongodbUri="<your Atlas connection string>" \
               azureOpenAiEndpoint="https://<your-resource>.openai.azure.com/" \
               foundryProjectEndpoint="<your Foundry project endpoint>" \
               foundryComputeCluster="<your compute cluster name>" \
               foundryBaseModel="<your base model>" \
               trainingRegion="<your region>"
```

The portal button prompts for the same parameters as a form — nothing to
hand-edit in the template itself. Required parameters have no default and
the deployment blade will refuse to submit until they're filled in.

Before the Job can pull the image the first time, either:
- push once via the CD workflow below so `ghcr.io/arshad98333/hafizal-ghidha:latest`
  exists, and set the GHCR package to **public** (package page → Package
  settings → Change visibility), or
- keep it private and add a registry pull secret afterward:
  ```bash
  az containerapp job registry set \
    --name <job-name> --resource-group <rg> \
    --server ghcr.io --username <github-username> --password <github PAT with read:packages>
  ```

### Grant the Job's managed identity access to Azure OpenAI

The Job deploys with a system-assigned managed identity (auth is AAD via
`DefaultAzureCredential`, matching `cold_chain/config.py` — never an API
key). After deployment, grant it access once:

```bash
principalId=$(az deployment group show -g <rg> -n main --query properties.outputs.jobPrincipalId.value -o tsv)

az role assignment create \
  --assignee "$principalId" \
  --role "Cognitive Services OpenAI User" \
  --scope /subscriptions/<sub-id>/resourceGroups/<openai-rg>/providers/Microsoft.CognitiveServices/accounts/<openai-resource>
```

Grant equivalent roles for the Foundry training compute if the identity
needs to submit SFT jobs (`train` stage).

## Continuous deployment (`.github/workflows/cd.yml`)

This workflow has two jobs, and they run on different triggers on purpose:

1. **`build-and-push`** runs on every push to `main`. It builds the Docker
   image and pushes `ghcr.io/arshad98333/hafizal-ghidha:<short-sha>` and
   `:latest` to GitHub Container Registry. This always runs, needs no Azure
   setup, and is what CI/CD status on `main` reflects day to day.
2. **`deploy`** runs **only on manual dispatch** (Actions tab → "Run
   workflow"), not on every push. It logs into Azure via OIDC, points the
   Container Apps Job at the new image, and — if a `run_stage` input is set
   — starts that stage/wave (`plan`, `generate`, `gate-a`, `train`, `gate-b`).

### Why the deploy job doesn't run automatically

This is a public, open-source repo. There is no live Azure subscription
wired into it by default — no `AZURE_CLIENT_ID`, `AZURE_TENANT_ID`, or
`AZURE_SUBSCRIPTION_ID` repo variables are set. If `deploy` ran on every
push (as it briefly did early on), the Azure login step fails on every
single run with:

```
Error: Login failed with Error: Using auth-type: SERVICE_PRINCIPAL.
Not all values are present. Ensure 'client-id' and 'tenant-id' are supplied.
```

That's not a code bug — it's Azure OIDC correctly refusing to authenticate
with nothing configured. Rather than show a permanent red X for a step
nobody has opted into, `deploy` is gated to `workflow_dispatch` only. Anyone
forking this repo can run `build-and-push` and the CI test suite with zero
setup, and only needs to do the one-time Azure OIDC setup below if they
actually want to deploy their own fork to their own Azure subscription.

### How to run a manual deploy, step by step

Once the one-time setup below is done, deploying is a few clicks — no local
`az` CLI needed:

1. Go to the **Actions** tab on GitHub.
2. Select **CD - Azure Container Apps** in the left sidebar.
3. Click **Run workflow** (top right).
4. Leave `run_stage` blank to just push the latest image to the Container
   Apps Job, or pick a stage (`plan`, `generate`, `gate-a`, `train`,
   `gate-b`) and a `wave` number to also start that stage immediately after
   deploying.
5. Click the green **Run workflow** button and watch it under the Actions
   tab — `build-and-push` runs first, then `deploy`.

If the five repo variables below aren't set yet, `deploy` will fail at the
Azure login step with the error shown above — that's expected until setup
is complete.

### One-time GitHub Actions setup

**1. Azure AD app registration + federated credential (OIDC, no secret):**

```bash
az ad app create --display-name "cold-chain-pipeline-gha"
appId=$(az ad app list --display-name "cold-chain-pipeline-gha" --query "[0].appId" -o tsv)
az ad sp create --id "$appId"

az ad app federated-credential create --id "$appId" --parameters '{
  "name": "github-main-branch",
  "issuer": "https://token.actions.githubusercontent.com",
  "subject": "repo:arshad98333/HAFIZAL-GHIDHA:ref:refs/heads/main",
  "audiences": ["api://AzureADTokenExchange"]
}'

# Add another federated-credential block with
# "subject": "repo:arshad98333/HAFIZAL-GHIDHA:environment:production"
# if you gate the deploy job behind a GitHub Environment (recommended --
# lets you require manual approval before deploying to Azure).

az role assignment create \
  --assignee "$appId" \
  --role "Container Apps Contributor" \
  --scope /subscriptions/<sub-id>/resourceGroups/<rg>
```

**2. GitHub repo settings → Secrets and variables → Actions:**

| Name | Type | Value |
|---|---|---|
| `AZURE_CLIENT_ID` | Variable | the app registration's `appId` |
| `AZURE_TENANT_ID` | Variable | `az account show --query tenantId -o tsv` |
| `AZURE_SUBSCRIPTION_ID` | Variable | `az account show --query id -o tsv` |
| `AZURE_RESOURCE_GROUP` | Variable | the resource group from provisioning |
| `CONTAINER_APP_JOB_NAME` | Variable | the `jobName` parameter used at deploy time (default `cold-chain-pipeline`) |

No Azure credential ever sits in GitHub as a secret — OIDC exchanges a
short-lived GitHub-issued token for an Azure AD token per run.

**3. (Optional, recommended) gate deploys behind a GitHub Environment:**
create a `production` environment (Settings → Environments) with required
reviewers. `cd.yml` already targets `environment: production` in the
`deploy` job, so this takes effect with no workflow changes.

## Updating pipeline configuration after deploy

Everything in `.env.example` maps to a Container Apps Job env var or secret.
To change one post-deploy without a full redeploy:

```bash
az containerapp job update --name <job-name> --resource-group <rg> \
  --set-env-vars "AZURE_OPENAI_DEPLOYMENT=gpt-5.4-mini"

# for secrets (MONGODB_URI, etc.):
az containerapp job secret set --name <job-name> --resource-group <rg> \
  --secrets "mongodb-uri=<new-connection-string>"
```

## Local equivalent

Everything above is optional if you'd rather run waves from your own
workstation against the same Atlas/Azure OpenAI resources — see the root
`README.md`'s "Step-by-step: getting a wave to run" section. The Container
Apps Job is for running waves unattended (e.g. triggered from CI, or on a
schedule via Azure Container Apps' cron trigger type) rather than a
requirement.
