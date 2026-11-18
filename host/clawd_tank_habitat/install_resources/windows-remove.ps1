$ErrorActionPreference='Stop'
$root=[IO.Path]::GetFullPath((Join-Path $env:LOCALAPPDATA 'Programs/ClawdTankHabitat'))
$marker=Join-Path $root '.habitat-install'
if ([IO.File]::ReadAllText($marker) -ne 'Clawd Tank desktop installation v1') { throw 'Unexpected install root' }
for ($attempt=0; $attempt -lt 40; $attempt++) {
    try {
        foreach ($name in @('releases','clawd-tank.exe','current','previous','host.lock')) {
            $target=[IO.Path]::GetFullPath((Join-Path $root $name))
            if ([IO.Path]::GetDirectoryName($target) -ne $root) { throw 'Unexpected path' }
            if (Test-Path -LiteralPath $target) { Remove-Item -LiteralPath $target -Recurse -Force }
        }
        Remove-Item -LiteralPath $marker
        if (-not (Get-ChildItem -LiteralPath $root -Force)) { Remove-Item -LiteralPath $root }
        break
    } catch { Start-Sleep -Milliseconds 250 }
}
# The caller runs this packaged script from memory so cleanup can release its own install directory.
