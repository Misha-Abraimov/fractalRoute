[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidatePattern('^[A-Za-z0-9_][A-Za-z0-9_.-]{0,127}$')]
    [string]$ImageTag,

    [ValidatePattern('^[a-z0-9]+(?:[._/-][a-z0-9]+)*$')]
    [string]$RepositoryName = 'fractal-route-worker',

    [ValidatePattern('^[a-z]{2}(?:-gov)?-[a-z]+-\d$')]
    [string]$Region = 'us-east-2',

    [string]$Profile = 'fractal-route'
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$env:AWS_PAGER = ''

if ($ImageTag -eq 'latest') {
    throw "Use a version or commit-based image tag instead of 'latest'."
}

foreach ($commandName in @('aws', 'docker')) {
    if (-not (Get-Command $commandName -ErrorAction SilentlyContinue)) {
        throw "Required command '$commandName' was not found on PATH."
    }
}

$profileArguments = @()
if ($Profile) {
    $profileArguments = @('--profile', $Profile)
}

$accountId = (& aws sts get-caller-identity @profileArguments --region $Region --query Account --output text).Trim()
if ($LASTEXITCODE -ne 0 -or $accountId -notmatch '^\d{12}$') {
    throw 'Could not obtain the AWS account ID from STS.'
}

& aws ecr describe-repositories @profileArguments --region $Region --repository-names $RepositoryName *> $null
if ($LASTEXITCODE -ne 0) {
    throw "ECR repository '$RepositoryName' does not exist or is not accessible. Create it explicitly before running this helper."
}

$registry = "$accountId.dkr.ecr.$Region.amazonaws.com"
$remoteTag = "$registry/${RepositoryName}:$ImageTag"
$localTag = "fractalroute-backend:$ImageTag"
$repositoryRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path

$loginPassword = & aws ecr get-login-password @profileArguments --region $Region
if ($LASTEXITCODE -ne 0 -or -not $loginPassword) {
    throw 'Could not obtain a temporary ECR login password.'
}
$loginPassword | & docker login --username AWS --password-stdin $registry
$loginPassword = $null
if ($LASTEXITCODE -ne 0) {
    throw 'Docker could not authenticate to ECR.'
}

Push-Location $repositoryRoot
try {
    & docker build --platform linux/amd64 --file Dockerfile --tag $localTag .
    if ($LASTEXITCODE -ne 0) {
        throw 'Docker image build failed.'
    }
}
finally {
    Pop-Location
}

& docker tag $localTag $remoteTag
if ($LASTEXITCODE -ne 0) {
    throw 'Docker image tagging failed.'
}

& docker push $remoteTag
if ($LASTEXITCODE -ne 0) {
    throw 'Docker image push failed.'
}

$digest = (& aws ecr describe-images @profileArguments --region $Region --repository-name $RepositoryName --image-ids "imageTag=$ImageTag" --query 'imageDetails[0].imageDigest' --output text).Trim()
if ($LASTEXITCODE -ne 0 -or $digest -notmatch '^sha256:[0-9a-f]{64}$') {
    throw 'Image pushed, but its immutable ECR digest could not be resolved.'
}

Write-Output "Tagged image URI: $remoteTag"
Write-Output "Immutable image URI: $registry/${RepositoryName}@$digest"
