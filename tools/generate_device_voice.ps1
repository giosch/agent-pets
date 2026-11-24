$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Speech
$voiceRoot = Join-Path $PSScriptRoot '../assets/device/voice'
$voiceConfig = Get-Content -LiteralPath (Join-Path $voiceRoot 'phrases.json') -Raw | ConvertFrom-Json
$petSpeech = New-Object System.Speech.Synthesis.SpeechSynthesizer
try {
    $petSpeech.SelectVoice($voiceConfig.voice)
    $petSpeech.Rate = $voiceConfig.rate
    $format = New-Object System.Speech.AudioFormat.SpeechAudioFormatInfo(12000, [System.Speech.AudioFormat.AudioBitsPerSample]::Sixteen, [System.Speech.AudioFormat.AudioChannel]::Mono)
    foreach ($phrase in $voiceConfig.phrases.PSObject.Properties) {
        $petSpeech.SetOutputToWaveFile((Join-Path $voiceRoot ($phrase.Name + '.wav')), $format)
        $petSpeech.Speak([string]$phrase.Value)
        $petSpeech.SetOutputToNull()
    }
} finally { $petSpeech.Dispose() }
