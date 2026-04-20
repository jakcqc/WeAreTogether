param(
  [switch]$Json
)

$pythonExe = "localchat/.venv/Scripts/python.exe"
if (-not (Test-Path $pythonExe)) {
  Write-Error "Could not find $pythonExe. Create the virtualenv first with 'uv sync'."
  exit 1
}

$args = @("localchat/scripts/bootstrap_local_client.py")
if ($Json) {
  $args += "--json"
}

& $pythonExe @args
exit $LASTEXITCODE
