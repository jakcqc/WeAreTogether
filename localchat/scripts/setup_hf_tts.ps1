param(
  [string]$EnvFile = "localchat/.env",
  [switch]$SetKey
)

$pythonExe = "localchat/.venv/Scripts/python.exe"
if (-not (Test-Path $pythonExe)) {
  Write-Error "Could not find $pythonExe. Create the virtualenv first."
  exit 1
}

$args = @("localchat/scripts/setup_hf_tts.py", "--env-file", $EnvFile)
if ($SetKey) {
  $args += "--set-key"
}

& $pythonExe @args
exit $LASTEXITCODE
