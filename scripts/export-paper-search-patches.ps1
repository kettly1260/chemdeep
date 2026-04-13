[CmdletBinding()]
param(
    [string]$RepoRoot = "",
    [string]$OutputDir = "",
    [string[]]$PatchCommits = @(
        "7b19b31",
        "3b4c682"
    )
)

$ErrorActionPreference = "Stop"

function Get-SafeSlug {
    param([string]$Value)

    $slug = $Value.ToLowerInvariant() -replace '[^a-z0-9]+', '-'
    $slug = $slug.Trim('-')
    if ([string]::IsNullOrWhiteSpace($slug)) {
        return "patch"
    }
    return $slug
}

if (-not $RepoRoot) {
    $RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
}

$RepoRoot = (Resolve-Path $RepoRoot).Path

if (-not $OutputDir) {
    $OutputDir = Join-Path $RepoRoot ".kilo\vendor-patches\paper-search-mcp-nodejs"
}

if (-not (Test-Path (Join-Path $RepoRoot ".git"))) {
    throw "Repo root '$RepoRoot' does not look like a git repository."
}

New-Item -ItemType Directory -Path $OutputDir -Force | Out-Null

$manifest = [ordered]@{
    generatedAt = (Get-Date).ToString("o")
    repoRoot = $RepoRoot
    vendoredPath = "paper-search-mcp-nodejs"
    upstreamRepo = "https://github.com/Dianel555/paper-search-mcp-nodejs"
    baselineAssumption = "v0.2.5 (verify before next sync)"
    patches = @()
}

$index = 1
foreach ($commit in $PatchCommits) {
    $subject = (git -C $RepoRoot show -s --format=%s $commit).Trim()
    if (-not $subject) {
        throw "Could not resolve commit '$commit'."
    }

    $shortCommit = $commit.Substring(0, [Math]::Min(7, $commit.Length))
    $safeSubject = Get-SafeSlug -Value $subject
    $patchPath = Join-Path $OutputDir ("{0:D2}-{1}-{2}.patch" -f $index, $shortCommit, $safeSubject)

    $patchContent = git -C $RepoRoot format-patch --stdout -1 $commit -- "paper-search-mcp-nodejs"
    if (-not $patchContent) {
        throw "git format-patch returned no content for '$commit'."
    }

    Set-Content -LiteralPath $patchPath -Value $patchContent -Encoding utf8

    $manifest.patches += [ordered]@{
        order = $index
        commit = $commit
        subject = $subject
        file = $patchPath
    }

    $index += 1
}

$manifestPath = Join-Path $OutputDir "manifest.json"
$manifest | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath $manifestPath -Encoding utf8

Write-Host "Exported $($manifest.patches.Count) patch(es) to $OutputDir"
Write-Host "Manifest: $manifestPath"
