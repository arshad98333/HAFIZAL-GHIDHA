# Deploy Web Stack to Azure (API Container App + Static Web App)
#
# Prerequisites:
#   az login
#   Docker (for API image build/push)
#   Node.js 20+ (for frontend build)
#   .env with MONGODB_URI, AZURE_OPENAI_ENDPOINT, FOUNDRY_* vars
#
# Usage (PowerShell):
#   .\scripts\deploy-azure-web.ps1
#   .\scripts\deploy-azure-web.ps1 -ResourceGroup gcc-coldchain-rg -Location uaenorth

param(
    [string]$ResourceGroup = "gcc-coldchain-rg",
    [string]$Location = "uaenorth",
    [string]$ApiAppName = "gcc-coldchain-api",
    [string]$StaticWebAppName = "gcc-coldchain-ui",
    [string]$ImageTag = "latest",
    [switch]$SkipInfra,
    [switch]$SkipApiImage,
    [switch]$SkipFrontend
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

function Get-DotEnvValue([string]$Key) {
    $line = Get-Content (Join-Path $Root ".env") -ErrorAction SilentlyContinue |
        Where-Object { $_ -match "^\s*$Key\s*=" } |
        Select-Object -First 1
    if (-not $line) { return $null }
    return ($line -split "=", 2)[1].Trim().Trim('"').Trim("'")
}

if (-not (Get-Command az -ErrorAction SilentlyContinue)) {
    Write-Error "Azure CLI (az) not found. Install: https://learn.microsoft.com/cli/azure/install-azure-cli"
}

$sub = az account show --query id -o tsv 2>$null
if (-not $sub) {
    Write-Error "Not logged in. Run: az login"
}

$mongodbUri = Get-DotEnvValue "MONGODB_URI"
$openAiEndpoint = Get-DotEnvValue "AZURE_OPENAI_ENDPOINT"
$foundryProject = Get-DotEnvValue "FOUNDRY_PROJECT_ENDPOINT"
$foundryCluster = Get-DotEnvValue "FOUNDRY_COMPUTE_CLUSTER"
$foundryModel = Get-DotEnvValue "FOUNDRY_BASE_MODEL"
$trainingRegion = Get-DotEnvValue "TRAINING_REGION"

if (-not $mongodbUri) { Write-Error "MONGODB_URI missing in .env" }
if (-not $openAiEndpoint) { Write-Error "AZURE_OPENAI_ENDPOINT missing in .env" }

$owner = (gh api user -q .login 2>$null)
if (-not $owner) { $owner = "arshad98333" }
$image = "ghcr.io/$($owner.ToLower())/hafizal-ghidha-api:$ImageTag"

if (-not $SkipApiImage) {
    Write-Host "Building API image: $image"
    docker build -f Dockerfile.api -t $image .
    Write-Host "Pushing to GHCR (ensure: gh auth token | docker login ghcr.io -u USER --password-stdin)"
    docker push $image
}

az group create --name $ResourceGroup --location $Location | Out-Null

if (-not $SkipInfra) {
    Write-Host "Deploying infra/web-stack.json..."
    az deployment group create `
        --resource-group $ResourceGroup `
        --template-file infra/web-stack.json `
        --parameters `
            apiAppName=$ApiAppName `
            staticWebAppName=$StaticWebAppName `
            apiImage=$image `
            mongodbUri=$mongodbUri `
            azureOpenAiEndpoint=$openAiEndpoint `
            foundryProjectEndpoint=$foundryProject `
            foundryComputeCluster=$foundryCluster `
            foundryBaseModel=$foundryModel `
            trainingRegion=$trainingRegion `
        --output none
} else {
    Write-Host "Updating Container App image..."
    az containerapp update --name $ApiAppName --resource-group $ResourceGroup --image $image | Out-Null
}

$apiFqdn = az containerapp show --name $ApiAppName --resource-group $ResourceGroup --query "properties.configuration.ingress.fqdn" -o tsv
$apiUrl = "https://$apiFqdn"
Write-Host "API URL: $apiUrl"

if (-not $SkipFrontend) {
    $swaHost = az staticwebapp show --name $StaticWebAppName --resource-group $ResourceGroup --query "defaultHostname" -o tsv
    $deployToken = az staticwebapp secrets list --name $StaticWebAppName --resource-group $ResourceGroup --query "properties.apiKey" -o tsv

    Push-Location (Join-Path $Root "frontend")
    $env:VITE_API_BASE_URL = $apiUrl
    npm ci 2>$null; if ($LASTEXITCODE -ne 0) { npm install }
    npm run build
    Pop-Location

    if (-not (Get-Command npx -ErrorAction SilentlyContinue)) {
        Write-Error "npx not found for SWA deploy"
    }

    Write-Host "Deploying frontend to Static Web App: https://$swaHost"
    npx --yes @azure/static-web-apps-cli deploy frontend/dist --deployment-token $deployToken --env production
}

Write-Host ""
Write-Host "=== Deployed ==="
Write-Host "API:      $apiUrl"
Write-Host "API docs: $apiUrl/docs"
Write-Host "UI:       https://$swaHost"
Write-Host "Simulation: https://$swaHost/simulation"
