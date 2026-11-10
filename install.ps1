# One-command install for Windows: uv, Python 3.12, dependencies and FFmpeg.
$ErrorActionPreference = "Stop"

$repoUrl = if ($env:LUNA_REPO_URL) { $env:LUNA_REPO_URL } else { "https://github.com/miqdadbadjuber/luna" }

if ($PSScriptRoot -and (Test-Path (Join-Path $PSScriptRoot "luna/app.py"))) {
    $lunaDir = $PSScriptRoot
} else {
    # Run through `irm | iex`, so there is no checkout yet.
    $lunaDir = if ($env:LUNA_DIR) { $env:LUNA_DIR } else { Join-Path $env:USERPROFILE "Luna" }
    $ref = if ($env:LUNA_REF) { $env:LUNA_REF } else { "main" }
    if (Test-Path (Join-Path $lunaDir ".git")) {
        git -C $lunaDir pull --ff-only
        if ($LASTEXITCODE -ne 0) { throw "Could not update Luna in $lunaDir." }
    } elseif ((Get-Command git -ErrorAction SilentlyContinue) -and -not (Test-Path (Join-Path $lunaDir "luna/app.py"))) {
        git clone --branch $ref $repoUrl $lunaDir
        if ($LASTEXITCODE -ne 0) {
            throw "Could not download Luna from $repoUrl. If the repository is private, clone it yourself and run .\install.ps1 there."
        }
    } else {
        # No git: unpack the source archive over $lunaDir. .env, .venv and media are not in it, so they survive.
        # shortcut: files removed upstream stay behind on an update, switch to git if that ever matters.
        Write-Host "Downloading Luna..."
        $zip = Join-Path $env:TEMP "luna-src.zip"
        $tmp = Join-Path $env:TEMP "luna-src"
        try {
            Invoke-WebRequest "$repoUrl/archive/$ref.zip" -OutFile $zip -UseBasicParsing -ErrorAction Stop
            if (Test-Path $tmp) { Remove-Item $tmp -Recurse -Force }
            Expand-Archive $zip -DestinationPath $tmp
            New-Item -ItemType Directory -Force $lunaDir | Out-Null
            Copy-Item (Join-Path (Get-ChildItem $tmp | Select-Object -First 1).FullName "*") $lunaDir -Recurse -Force
        } catch {
            throw "Could not download Luna from $repoUrl. $($_.Exception.Message)"
        } finally {
            Remove-Item $zip, $tmp -Recurse -Force -ErrorAction SilentlyContinue
        }
    }
}
Set-Location $lunaDir

if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    Write-Host "Installing uv..."
    # Download first, then run: piping into Invoke-Expression cannot be checksummed and
    # hides a network failure. Pin UV_VERSION and verify a hash for full reproducibility.
    $uvInstaller = Join-Path $env:TEMP "uv-install.ps1"
    try {
        Invoke-RestMethod https://astral.sh/uv/install.ps1 -OutFile $uvInstaller -ErrorAction Stop
        powershell -NoProfile -ExecutionPolicy Bypass -File $uvInstaller
        if ($LASTEXITCODE -ne 0) { throw "The uv installer failed (exit $LASTEXITCODE)." }
    } finally {
        if (Test-Path $uvInstaller) { Remove-Item $uvInstaller -Force -ErrorAction SilentlyContinue }
    }
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
.venv\Scripts\python.exe -c "from luna.ffmpeg_setup import ensure_ffmpeg; ensure_ffmpeg()"
if ($LASTEXITCODE -ne 0) { throw "Could not set up FFmpeg." }

Write-Host "Luna is installed in $lunaDir. Start it again later with start.bat"
if ($env:LUNA_NO_START -ne "1") { & .\start.bat }
