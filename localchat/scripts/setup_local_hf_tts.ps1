param(
  [string]$Model = "Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice",
  [string]$Text = "LocalChat local Hugging Face TTS test.",
  [string]$Voice = "Chelsie",
  [string]$Output = "localchat/downloads/local_hf_tts_probe.wav"
)

$pythonExe = "localchat/.venv/Scripts/python.exe"
if (-not (Test-Path $pythonExe)) {
  Write-Error "Could not find $pythonExe. Create the virtualenv first."
  exit 1
}

$args = @(
  "localchat/scripts/setup_local_hf_tts.py",
  "--model", $Model,
  "--text", $Text,
  "--output", $Output
)
if ($Voice -and $Voice.Trim().Length -gt 0) {
  $args += @("--voice", $Voice)
}

& $pythonExe @args
exit $LASTEXITCODE
