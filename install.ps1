# One-command install for Windows: uv, Python 3.12, dependencies and FFmpeg.
$ErrorActionPreference = "Stop"

$repoUrl = if ($env:LUNA_REPO_URL) { $env:LUNA_REPO_URL } else { "https://github.com/miqdadbadjuber/luna" }

$isUpdate = $false
if ($PSScriptRoot -and (Test-Path (Join-Path $PSScriptRoot "luna/app.py"))) {
    $lunaDir = $PSScriptRoot
    $isUpdate = Test-Path (Join-Path $lunaDir ".venv\Scripts\python.exe")
} else {
    # Run through `irm | iex`, so there is no checkout yet.
    $lunaDir = if ($env:LUNA_DIR) { $env:LUNA_DIR } else { Join-Path $env:USERPROFILE "Luna" }
    $ref = if ($env:LUNA_REF) { $env:LUNA_REF } else { "main" }
    if (Test-Path (Join-Path $lunaDir ".git")) {
        $isUpdate = $true
        Write-Host "Updating Luna in $lunaDir..."
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
        $isUpdate = Test-Path (Join-Path $lunaDir "luna/app.py")
        $downloadMsg = if ($isUpdate) { "Updating Luna in $lunaDir..." } else { "Downloading Luna..." }
        Write-Host $downloadMsg
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

# A Desktop and Start Menu shortcut, so starting Luna again needs no terminal.
$shortcutsCreated = $false
try {
    $shell = New-Object -ComObject WScript.Shell
    foreach ($dir in @([Environment]::GetFolderPath("Desktop"), [Environment]::GetFolderPath("Programs"))) {
        if (-not $dir) { continue }
        $lnk = $shell.CreateShortcut((Join-Path $dir "Luna.lnk"))
        $lnk.TargetPath = Join-Path $lunaDir "start.bat"
        $lnk.WorkingDirectory = $lunaDir
        $lnk.Save()
    }
    $shortcutsCreated = $true
} catch {
    Write-Warning "Could not create the Luna shortcut: $($_.Exception.Message)"
}

$actionWord = if ($isUpdate) { "update" } else { "installation" }
Write-Host ""
Write-Host "============================================================" -ForegroundColor DarkGray
Write-Host "  Luna $actionWord complete!" -ForegroundColor Green
Write-Host "============================================================" -ForegroundColor DarkGray
Write-Host "  Location : $lunaDir"
if ($shortcutsCreated) {
    Write-Host "  Launcher : 'Luna' shortcut (Desktop & Start Menu) or .\start.bat"
} else {
    Write-Host "  Launcher : .\start.bat"
}
Write-Host "  Settings : .env and saved Workspace media are kept across updates."
Write-Host "  Update   : Close Luna first, then re-run the same PowerShell install command."
Write-Host "============================================================" -ForegroundColor DarkGray
Write-Host ""

if ($env:LUNA_NO_START -ne "1") {
    $shouldLaunch = $true
    $canPrompt = $false
    try {
        $canPrompt = [Environment]::UserInteractive -and -not [Console]::IsInputRedirected
    } catch {
        $canPrompt = $false
    }
    if ($canPrompt -and $env:LUNA_AUTO_START -ne "1") {
        $reply = Read-Host "Press Enter to launch Luna now (or type N to exit)"
        if ($reply -and $reply.Trim().ToLowerInvariant() -in @("n", "no")) {
            $shouldLaunch = $false
        }
    }
    if ($shouldLaunch) {
        Write-Host "Starting Luna..." -ForegroundColor Cyan
        & .\start.bat
    } else {
        Write-Host "Launch skipped. Open Luna anytime from the Desktop/Start Menu shortcut or .\start.bat."
    }
}
