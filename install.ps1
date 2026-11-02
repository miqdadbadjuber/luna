# One-command install for Windows: uv, Python 3.12, dependencies and FFmpeg.
$ErrorActionPreference = "Stop"

$repoUrl = if ($env:LUNA_REPO_URL) { $env:LUNA_REPO_URL } else { "https://github.com/miqdadbadjuber/luna" }

if ($PSScriptRoot -and (Test-Path (Join-Path $PSScriptRoot "app.py"))) {
    $lunaDir = $PSScriptRoot
} else {
    # Run through `irm | iex`, so there is no checkout yet.
    $lunaDir = if ($env:LUNA_DIR) { $env:LUNA_DIR } else { Join-Path $env:USERPROFILE "Luna" }
    if (-not (Get-Command git -ErrorAction SilentlyContinue)) { throw "git is required to download Luna." }
    if (Test-Path (Join-Path $lunaDir ".git")) {
        git -C $lunaDir pull --ff-only
    } else {
        git clone $repoUrl $lunaDir
    }
    if ($LASTEXITCODE -ne 0) {
        throw "Could not download Luna from $repoUrl. If the repository is private, clone it yourself and run .\install.ps1 there."
    }
}
Set-Location $lunaDir

if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    Write-Host "Installing uv..."
    Invoke-RestMethod https://astral.sh/uv/install.ps1 | Invoke-Expression
    $env:Path = "$env:USERPROFILE\.local\bin;$env:Path"
}

Write-Host "Installing Python and dependencies..."
uv venv .venv --python 3.12 --allow-existing
if ($LASTEXITCODE -ne 0) { throw "Could not create the virtual environment." }
uv pip install --python .venv\Scripts\python.exe -r requirements.txt
if ($LASTEXITCODE -ne 0) { throw "Could not install dependencies." }

# Keys are entered in Settings. Never overwrite a file that may already hold them.
if (-not (Test-Path .env)) { Copy-Item .env.example .env }

Write-Host "Checking FFmpeg..."
.venv\Scripts\python.exe -c "from ffmpeg_setup import ensure_ffmpeg; ensure_ffmpeg()"
if ($LASTEXITCODE -ne 0) { throw "Could not set up FFmpeg." }

Write-Host "Luna is installed in $lunaDir. Start it again later with start.bat"
if ($env:LUNA_NO_START -ne "1") { & .\start.bat }
