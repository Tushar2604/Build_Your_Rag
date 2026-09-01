# Local development stack: API + WhatsApp bridge + frontend, supervised.
#
# WHY THIS EXISTS
#
# WhatsApp replies need THREE processes alive, not one:
#
#   API    :8000  receives the bridge's events and generates the reply
#   Bridge :8081  a separate Node process holding the actual WhatsApp socket
#   Vite   :5173  the console UI (not needed for WhatsApp itself)
#
# The bridge is the one people forget. It is not part of the Python app -- it is
# a Baileys sidecar in its own process -- so `uvicorn` alone gives you a console
# that looks completely healthy while no WhatsApp message can physically
# arrive. The symptom is always the same and always misleading: "the assistant
# stopped replying", when in truth nothing was ever delivered to reply to.
#
# In the container, `scripts/start.sh` starts the bridge alongside the API and
# restarts it when it exits. Running locally without Docker, nothing did that --
# which is why replies kept stopping whenever the bridge quietly went away.
# This is the local equivalent of that supervision.
#
#   .\scripts\dev.ps1              everything
#   .\scripts\dev.ps1 -NoFrontend  API + bridge only
#   Ctrl-C                         stops all of them together

param(
    [switch]$NoFrontend,
    [switch]$NoBridge
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

# --- .env, read without needing a dependency to read it --------------------
# The bridge is a Node process that reads the environment it inherits, so these
# have to be set on THIS process before anything is launched.
if (-not (Test-Path ".env")) {
    Write-Host "No .env found -- copy .env.example to .env first." -ForegroundColor Yellow
    exit 1
}
foreach ($line in Get-Content ".env") {
    if ($line -match '^\s*#' -or $line -notmatch '=') { continue }
    $name, $value = $line -split '=', 2
    $name = $name.Trim()
    $value = $value.Trim()

    # A quoted value keeps everything inside the quotes. An unquoted one ends
    # at the first whitespace-preceded '#', which is the dotenv convention --
    # and skipping this step is not cosmetic: `APP_ENV=development  # dev|prod`
    # otherwise sets APP_ENV to the comment as well, and because a process
    # variable outranks the .env file, the API refuses to start with a
    # validation error pointing at a line that looks perfectly fine.
    $quoted = ($value.StartsWith([char]34) -and $value.EndsWith([char]34)) -or
              ($value.StartsWith([char]39) -and $value.EndsWith([char]39))
    if ($quoted) {
        $value = $value.Substring(1, $value.Length - 2)
    } elseif ($value -match '\s#') {
        $value = ($value -split '\s#', 2)[0].Trim()
    }

    if ($name) { Set-Item -Path "Env:$name" -Value $value }
}
$env:BRIDGE_API_BASE = "http://127.0.0.1:8000"

$python = Join-Path $root ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) { $python = "python" }

# Each child is an executable plus its arguments, never a string to be parsed.
# PowerShell jobs do not close over the parent's variables, so everything is
# passed in explicitly - and keeping the exe separate from its arguments avoids
# quoting a path that contains spaces.
$commands = [ordered]@{}
$commands["api"] = @{
    dir  = $root
    exe  = $python
    args = @("-m", "uvicorn", "src.interfaces.api.app:app",
             "--host", "127.0.0.1", "--port", "8000")
}

if (-not $NoBridge) {
    if ($env:BRIDGE_TOKEN) {
        $commands["bridge"] = @{
            dir  = (Join-Path $root "whatsapp-bridge")
            exe  = "node"
            args = @("src/index.js")
        }
    } else {
        # Skipped exactly as the container does: with no token the API reports
        # the feature as unconfigured and everything else works unchanged.
        Write-Host "BRIDGE_TOKEN unset - WhatsApp bridge disabled." -ForegroundColor Yellow
    }
}
if (-not $NoFrontend) {
    $commands["web"] = @{
        dir  = (Join-Path $root "frontend")
        exe  = "npx"
        args = @("vite", "--port", "5173", "--host", "127.0.0.1")
    }
}

$jobs = @()
foreach ($name in $commands.Keys) {
    Write-Host "starting $name" -ForegroundColor DarkGray
    $spec = $commands[$name]
    $jobs += Start-Job -Name $name -ArgumentList $spec.dir, $spec.exe, $spec.args -ScriptBlock {
        param($workdir, $exe, $exeArgs)
        Set-Location $workdir
        # A restart loop per child. A bridge that dies - WhatsApp dropping the
        # socket, an unhandled rejection - comes back on its own instead of
        # silently ending replies until somebody happens to notice.
        while ($true) {
            try { & $exe @exeArgs 2>&1 } catch { Write-Output "exited: $_" }
            Write-Output "restarting in 3s..."
            Start-Sleep -Seconds 3
        }
    }
}

Write-Host ""
Write-Host "  API      http://127.0.0.1:8000/docs" -ForegroundColor Cyan
if ($commands.Contains("bridge")) {
    Write-Host "  Bridge   http://127.0.0.1:8081/healthz  (needs the x-bridge-token header)" -ForegroundColor Green
}
if ($commands.Contains("web")) {
    Write-Host "  Console  http://127.0.0.1:5173" -ForegroundColor Magenta
}
Write-Host ""
Write-Host "Streaming logs. Ctrl-C stops everything." -ForegroundColor DarkGray
Write-Host ""

try {
    while ($true) {
        foreach ($job in $jobs) {
            Receive-Job -Job $job | ForEach-Object { "[$($job.Name)] $_" }
        }
        Start-Sleep -Milliseconds 400
    }
} finally {
    # Without this, Ctrl-C leaves the bridge holding an open WhatsApp socket and
    # the next run cannot bind :8081.
    Write-Host "`nstopping..." -ForegroundColor DarkGray
    $jobs | Stop-Job -ErrorAction SilentlyContinue
    $jobs | Remove-Job -Force -ErrorAction SilentlyContinue
}
