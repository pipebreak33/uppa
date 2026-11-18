<#
 Avinstallera Uppa på Windows (fungerar även i pwsh på macOS/Linux):
   irm https://raw.githubusercontent.com/pipebreak33/uppa/main/uninstall.ps1 | iex
 Från en lokal kopia:  ./uninstall.ps1

 Tar bort programmet (~/.uppa/uppa.py), kommandot uppa och PATH-posten.
 Behåller Uppas cache och logg (~/.uppa).
 $env:UPPA_PURGE = '1' tar bort även .uppa med dina data. $env:UPPA_YES = '1' hoppar över frågan.
#>
$ErrorActionPreference = 'Stop'
$Clock = [Diagnostics.Stopwatch]::StartNew()
$OnWindows = ($PSVersionTable.PSEdition -ne 'Core') -or $IsWindows
$Dir = Join-Path $HOME '.uppa'
$Bin = Join-Path $Dir 'bin'
$Shim = if ($OnWindows) { Join-Path $Bin 'uppa.cmd' } else { Join-Path $HOME '.local/bin/uppa' }

function Say($m) { Write-Host "  ▲ $m" -ForegroundColor Green }
function Ask($q) { $s = Read-Host "  $q [j/N]"; return ($s -match '^(j|ja|y|yes)$') }

$targets = @()
if ($env:UPPA_PURGE -eq '1') {
    if (Test-Path $Dir) { $targets += $Dir }
} else {
    foreach ($p in @('uppa.py', 'bin')) { $x = Join-Path $Dir $p; if (Test-Path $x) { $targets += $x } }
}
# startkommandot på macOS/Linux: bara om det är vårt (pekar på ~/.uppa)
if (-not $OnWindows -and (Test-Path $Shim) -and ((Get-Content $Shim -Raw) -like "*/.uppa/*")) { $targets += $Shim }
$user = if ($OnWindows) { [Environment]::GetEnvironmentVariable('Path', 'User') } else { '' }
if (-not $user) { $user = '' }
$inPath = ($user -split ';') -contains $Bin

if (-not $targets -and -not $inPath) { Say 'Uppa är inte installerad här. Inget att ta bort.'; return }
Write-Host "`n  Det här tas bort:"
$targets | ForEach-Object { Write-Host "    $_" }
if ($inPath) { Write-Host "    $Bin i din PATH" }
if ($env:UPPA_PURGE -ne '1') { Write-Host '  Behålls: Uppas cache och logg (~/.uppa).' }
Write-Host ''
if ($env:UPPA_YES -ne '1') {
    if (-not (Ask 'Avinstallera Uppa?')) { Say 'Avbrutet. Ingenting har tagits bort.'; return }
}

foreach ($t in $targets) { Remove-Item $t -Recurse -Force }
if ($inPath) {
    [Environment]::SetEnvironmentVariable('Path', (($user -split ';' | Where-Object { $_ -and $_ -ne $Bin }) -join ';'), 'User')
}
if ((Test-Path $Dir) -and -not (Get-ChildItem $Dir -Force)) { Remove-Item $Dir -Force }

$Clock.Stop()
Write-Host "`n  ✔ Uppa är avinstallerad ($([int]$Clock.Elapsed.TotalSeconds) s).`n" -ForegroundColor Green
