# Deploying to Azure Container Apps

This pipeline ships as an **Azure Container Apps Job**, not a web app. Every
stage (`plan`, `generate`, `gate-a`, `train`, `gate-b`) is a separate,
resumable CLI invocation (see `README.md`), which is exactly what a
manually-triggered Container Apps Job is for: run one execution, it does one
stage of one wave, and exits. There's no HTTP listener to keep warm and no
idle cost between waves.

`infra/main.json` provisions everything: a Log Analytics workspace, a
Container Apps managed environment, and the Job itself.
`.github/workflows/cd.yml` builds the image on every push to `main`, pushes
it to GitHub Container Registry, and points the Job at the new image.

## One-click provisioning

Click the button in `README.md` ("Deploy to Azure"), or run:

```bash
az deployment group create \
  --resource-group <your-resource-group> \
  --template-file infra/main.json \
  --parameters containerImage=ghcr.io/<owner>/<repo>:latest \
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
- push once via the CD workflow below so `ghcr.io/<owner>/<repo>:latest`
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

On every push to `main`, this workflow:

1. Builds the Docker image and pushes `ghcr.io/<owner>/<repo>:<short-sha>`
   and `:latest`.
2. Logs into Azure via OIDC (no stored secret — see setup below).
3. Runs `az containerapp job update --image ...` so the next execution of
   the Job uses the new image. It does **not** start an execution by itself;
   updating the image doesn't run a wave.
4. If manually dispatched (Actions tab → "Run workflow") with a `run_stage`
   input set, it also runs `az containerapp job start` with that stage and
   wave — this is how you kick off `plan --wave 1`, `generate --wave 1`, etc.
   from GitHub instead of a local `az` CLI.

### One-time GitHub Actions setup

**1. Azure AD app registration + federated credential (OIDC, no secret):**

```bash
az ad app create --display-name "cold-chain-pipeline-gha"
appId=$(az ad app list --display-name "cold-chain-pipeline-gha" --query "[0].appId" -o tsv)
az ad sp create --id "$appId"

az ad app federated-credential create --id "$appId" --parameters '{
  "name": "github-main-branch",
  "issuer": "https://token.actions.githubusercontent.com",
  "subject": "repo:<owner>/<repo>:ref:refs/heads/main",
  "audiences": ["api://AzureADTokenExchange"]
}'

# Add another federated-credential block with
# "subject": "repo:<owner>/<repo>:environment:production"
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
