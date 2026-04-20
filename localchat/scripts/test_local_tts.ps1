param(
  [string]$Text = "LocalChat local voice reader test",
  [string]$Output = "localchat/downloads/local_tts_test.wav",
  [string]$Voice = ""
)

try {
  Add-Type -AssemblyName System.Speech
} catch {
  Write-Error "System.Speech is not available on this machine: $($_.Exception.Message)"
  exit 1
}

$synth = New-Object System.Speech.Synthesis.SpeechSynthesizer
$availableVoices = @()
try {
  $availableVoices = @($synth.GetInstalledVoices() | ForEach-Object { $_.VoiceInfo.Name })
} catch {
  $availableVoices = @()
}

if ($availableVoices.Count -eq 0) {
  Write-Error "No local Windows speech voices are installed. Install at least one Windows Text-to-Speech voice and rerun this script."
  $synth.Dispose()
  exit 2
}

if ($Voice -and $Voice.Trim().Length -gt 0) {
  try {
    $synth.SelectVoice($Voice)
  } catch {
    Write-Error "Requested voice '$Voice' was not found. Available voices: $($availableVoices -join ', ')"
    $synth.Dispose()
    exit 1
  }
}

$outputPath = [System.IO.Path]::GetFullPath($Output)
$outputDir = Split-Path -Path $outputPath -Parent
if (-not (Test-Path $outputDir)) {
  New-Item -ItemType Directory -Path $outputDir -Force | Out-Null
}

try {
  $synth.SetOutputToWaveFile($outputPath)
  $synth.Speak($Text)
  $synth.SetOutputToDefaultAudioDevice()
} catch {
  Write-Error "Local TTS generation failed: $($_.Exception.Message)"
  $synth.Dispose()
  exit 1
}

$synth.Dispose()
Write-Output "OK: local TTS audio generated at $outputPath"
exit 0
