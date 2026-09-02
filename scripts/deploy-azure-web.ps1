# Deploy Web Stack to Azure (API Container App + Static Web App)
#
# No local Docker required - builds the API image in Azure Container Registry (az acr build).
# No GitHub CLI required - owner is read from git remote.
#
# Prerequisites:
#   az login
#   Node.js 20+ (frontend build + SWA deploy)
#   .env with MONGODB_URI, AZURE_OPENAI_ENDPOINT
#
# Usage (PowerShell):
#   .\scripts\deploy-azure-web.ps1
#   .\scripts\deploy-azure-web.ps1 -ResourceGroup gcc-coldchain-rg -Location uaenorth

param(
    [string]$ResourceGroup = "gcc-coldchain-rg",
    [string]$Location = "uaenorth",
    [string]$StaticWebLocation = "westeurope",
    [string]$ApiAppName = "gcc-coldchain-api",
    [string]$StaticWebAppName = "gcc-coldchain-ui",
    [string]$ImageTag = "latest",
    [ValidateSet("Acr", "Docker", "Ghcr")]
    [string]$BuildMethod = "Acr",
    [string]$AcrName = "",
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

function Get-GitHubOwner {
    try {
        $remote = (git -C $Root config --get remote.origin.url 2>$null)
        if ($remote -match "github\.com[:/]([^/]+)") {
            return $Matches[1]
        }
    } catch {}
    return "arshad98333"
}

function Test-Command([string]$Name) {
    return [bool](Get-Command $Name -ErrorAction SilentlyContinue)
}

function Resolve-PlaceholderValue([string]$Value, [string]$Fallback) {
    if (-not $Value) { return $Fallback }
    if ($Value -match '^\s*<[^>]+>\s*$') { return $Fallback }
    return $Value
}

function Write-ArmParametersFile([string]$Path, [hashtable]$Values) {
    $parameters = @{}
    foreach ($key in $Values.Keys) {
        $parameters[$key] = @{ value = $Values[$key] }
    }
    $doc = [ordered]@{
        '$schema'        = 'https://schema.management.azure.com/schemas/2019-04-01/deploymentParameters.json#'
        contentVersion   = '1.0.0.0'
        parameters       = $parameters
    }
    $json = $doc | ConvertTo-Json -Depth 6
    [System.IO.File]::WriteAllText($Path, $json, [System.Text.UTF8Encoding]::new($false))
}

if (-not (Test-Command az)) {
    Write-Error 'Azure CLI (az) not found. Install: https://learn.microsoft.com/cli/azure/install-azure-cli'
}

$sub = az account show --query id -o tsv 2>$null
if (-not $sub) {
    Write-Error 'Not logged in. Run: az login'
}

$mongodbUri = Get-DotEnvValue "MONGODB_URI"
$openAiEndpoint = Get-DotEnvValue "AZURE_OPENAI_ENDPOINT"
$foundryProject = Get-DotEnvValue "FOUNDRY_PROJECT_ENDPOINT"
if (-not $foundryProject) { $foundryProject = $openAiEndpoint }
$foundryCluster = Resolve-PlaceholderValue (Get-DotEnvValue "FOUNDRY_COMPUTE_CLUSTER") "unused"
$foundryModel = Resolve-PlaceholderValue (Get-DotEnvValue "FOUNDRY_BASE_MODEL") "unused"
$trainingRegion = Get-DotEnvValue "TRAINING_REGION"
if (-not $trainingRegion) { $trainingRegion = $Location }

if (-not $mongodbUri) { Write-Error 'MONGODB_URI missing in .env' }
if (-not $openAiEndpoint) { Write-Error 'AZURE_OPENAI_ENDPOINT missing in .env' }

$acrServer = ""
$acrUsername = ""
$acrPassword = ""
$image = ""

if (-not $SkipApiImage) {
    if ($BuildMethod -eq "Acr") {
        if (-not $AcrName) {
            $AcrName = ("gccchain" + ($sub -replace "-", "").Substring(0, 8)).ToLower()
        }
        if ($AcrName.Length -lt 5 -or $AcrName.Length -gt 50) {
            Write-Error 'ACR name must be 5-50 alphanumeric characters. Pass -AcrName explicitly.'
        }

        az group create --name $ResourceGroup --location $Location | Out-Null

        $acrExists = $false
        try {
            az acr show --name $AcrName --resource-group $ResourceGroup -o none 2>$null
            if ($LASTEXITCODE -eq 0) { $acrExists = $true }
        } catch {}

        if (-not $acrExists) {
            Write-Host "Creating Azure Container Registry: $AcrName"
            az acr create --name $AcrName --resource-group $ResourceGroup --sku Basic --location $Location --admin-enabled true | Out-Null
            if ($LASTEXITCODE -ne 0) { throw 'az acr create failed' }
        }

        Write-Host "Building API image in Azure (no local Docker): $AcrName.azurecr.io/api:$ImageTag"
        az acr build --registry $AcrName --image "api:$ImageTag" --file Dockerfile.api .
        if ($LASTEXITCODE -ne 0) { throw 'az acr build failed' }

        $acrServer = "$AcrName.azurecr.io"
        $acrUsername = az acr credential show --name $AcrName --query username -o tsv
        $acrPassword = az acr credential show --name $AcrName --query "passwords[0].value" -o tsv
        $image = "$acrServer/api:$ImageTag"
    }
    elseif ($BuildMethod -eq "Docker") {
        if (-not (Test-Command docker)) {
            Write-Error 'Docker not found. Use default -BuildMethod Acr (cloud build, no Docker) or install Docker Desktop.'
        }
        $acrServer = ""
        $image = "gcc-coldchain-api-local:$ImageTag"
        Write-Host "Building API image locally: $image"
        docker build -f Dockerfile.api -t $image .
        if ($LASTEXITCODE -ne 0) { throw 'docker build failed' }
        Write-Error 'Local Docker images cannot be pulled by Azure Container Apps. Use -BuildMethod Acr instead.'
    }
    else {
        if (-not (Test-Command docker)) {
            Write-Error 'Docker not found. Use -BuildMethod Acr (default, no Docker required).'
        }
        $owner = Get-GitHubOwner
        $image = "ghcr.io/$($owner.ToLower())/hafizal-ghidha-api:$ImageTag"
        Write-Host "Building API image for GHCR: $image"
        docker build -f Dockerfile.api -t $image .
        if ($LASTEXITCODE -ne 0) { throw 'docker build failed' }
        if (Test-Command gh) {
            $token = gh auth token 2>$null
            if ($token) {
                $token | docker login ghcr.io -u $owner --password-stdin | Out-Null
            }
        }
        docker push $image
        if ($LASTEXITCODE -ne 0) { throw 'docker push failed - run: gh auth login' }
    }
}

if (-not $image) {
    Write-Error 'No API image resolved. Remove -SkipApiImage or fix build step.'
}

az group create --name $ResourceGroup --location $Location | Out-Null

# ARM expects {"parameters": {"name": {"value": "..."}}} not flat key/value JSON.
$paramFile = Join-Path $env:TEMP "hafizal-web-deploy-params.json"
$paramValues = @{
    apiAppName             = $ApiAppName
    staticWebAppName       = $StaticWebAppName
    staticWebLocation      = $StaticWebLocation
    apiImage               = $image
    mongodbUri             = $mongodbUri
    azureOpenAiEndpoint    = $openAiEndpoint
    foundryProjectEndpoint = $foundryProject
    foundryComputeCluster  = $foundryCluster
    foundryBaseModel       = $foundryModel
    trainingRegion         = $trainingRegion
    acrServer              = $acrServer
    acrUsername            = $acrUsername
    acrPassword            = $acrPassword
}
Write-ArmParametersFile -Path $paramFile -Values $paramValues

if (-not $SkipInfra) {
    Write-Host 'Deploying infra/web-stack.json...'
    az deployment group create `
        --resource-group $ResourceGroup `
        --template-file infra/web-stack.json `
        --parameters "@$paramFile" `
        --output none
    if ($LASTEXITCODE -ne 0) {
        Write-Host 'Tip: image is already in ACR. Retry infra only with:'
        Write-Host "  .\scripts\deploy-azure-web.ps1 -SkipApiImage"
        throw 'ARM deployment failed'
    }
} else {
    Write-Host 'Updating Container App image...'
    if ($acrServer) {
        az containerapp registry set `
            --name $ApiAppName `
            --resource-group $ResourceGroup `
            --server $acrServer `
            --username $acrUsername `
            --password $acrPassword | Out-Null
    }
    az containerapp update --name $ApiAppName --resource-group $ResourceGroup --image $image | Out-Null
    if ($LASTEXITCODE -ne 0) { throw 'containerapp update failed' }
}

Remove-Item $paramFile -Force -ErrorAction SilentlyContinue

$apiFqdn = az containerapp show --name $ApiAppName --resource-group $ResourceGroup --query "properties.configuration.ingress.fqdn" -o tsv
if (-not $apiFqdn) {
    Write-Host 'Waiting for API ingress...'
    Start-Sleep -Seconds 15
    $apiFqdn = az containerapp show --name $ApiAppName --resource-group $ResourceGroup --query "properties.configuration.ingress.fqdn" -o tsv
}
$apiUrl = "https://$apiFqdn"
Write-Host "API URL: $apiUrl"

$swaHost = ""

if (-not $SkipFrontend) {
    if (-not (Test-Command npm)) {
        Write-Error 'Node.js/npm not found. Install Node 20+: https://nodejs.org/'
    }

    $swaHost = az staticwebapp show --name $StaticWebAppName --resource-group $ResourceGroup --query "defaultHostname" -o tsv
    $deployToken = az staticwebapp secrets list --name $StaticWebAppName --resource-group $ResourceGroup --query "properties.apiKey" -o tsv

    Push-Location (Join-Path $Root "frontend")
    $env:VITE_API_BASE_URL = $apiUrl
    npm ci 2>$null
    if ($LASTEXITCODE -ne 0) { npm install }
    if ($LASTEXITCODE -ne 0) { throw 'npm install failed' }
    npm run build
    if ($LASTEXITCODE -ne 0) { throw 'npm run build failed' }
    Pop-Location

    Write-Host "Deploying frontend to Static Web App: https://$swaHost"
    npx --yes @azure/static-web-apps-cli deploy frontend/dist --deployment-token $deployToken --env production
    if ($LASTEXITCODE -ne 0) { throw 'Static Web App deploy failed' }
}

Write-Host ''
Write-Host '=== Deployed ==='
Write-Host "API:        $apiUrl"
Write-Host "API docs:   $apiUrl/docs"
Write-Host "Simulate:   $apiUrl/simulate (POST)"
if ($swaHost) {
    Write-Host "UI:         https://$swaHost"
    Write-Host "Simulation: https://$swaHost/simulation"
}
Write-Host ''
Write-Host 'Verify:'
Write-Host "  curl $apiUrl/health"
