# ship.ps1 - test, commit, and push in one step.
# Usage:   powershell -File scripts/ship.ps1 "commit message"
# NOTE:    use "-File" (not `powershell scripts/ship.ps1 ...`) — PS 5.1's
#          legacy arg parser truncates quoted messages at spaces/commas.
# Result:  backend tests pass -> stage all -> commit -> push to origin.
# Safety:  exits non-zero WITHOUT committing if tests fail or nothing is staged.
param([string]$message = "chore: sync local work")

$ErrorActionPreference = "Stop"
$root = git rev-parse --show-toplevel
if (-not $root) { Write-Error "Not inside a git repository."; exit 1 }
Push-Location $root

Write-Host "==> Running backend tests ..."
python -m pytest backend/tests -q
if ($LASTEXITCODE -ne 0) {
    Write-Error "Tests FAILED - aborting. Nothing was committed or pushed."
    Pop-Location
    exit 1
}

Write-Host "==> Staging all changes ..."
git add -A
$staged = (git diff --cached --name-only | Measure-Object -Line).Lines
if ($staged -eq 0) { Write-Host "Nothing to commit - working tree matches HEAD."; Pop-Location; exit 0 }
git diff --cached --name-only | ForEach-Object { Write-Host "   $_" }

Write-Host "==> Committing: $message"
git commit -m $message
if ($LASTEXITCODE -ne 0) { Write-Error "Commit failed."; Pop-Location; exit 1 }

$branch = git branch --show-current
Write-Host "==> Pushing to origin/$branch ..."
git push origin $branch
Pop-Location
Write-Host "Done - remote is up to date."