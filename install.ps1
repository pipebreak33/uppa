<#
 uppa för Windows (Windows PowerShell 5.1 eller PowerShell 7). Fungerar även i pwsh på macOS/Linux.
   irm https://raw.githubusercontent.com/pipebreak33/uppa/main/install.ps1 | iex
 Från en lokal kopia:  ./install.ps1
 Styr källan med $env:UPPA_REPO = 'ägare/repo' och $env:UPPA_BRANCH = 'gren eller tagg'.

 uppa är ett Python-skript utan beroenden. Saknas Python 3.8+ installeras det:
   1. med winget (per användare), annars
   2. direkt från python.org (per användare, inga adminrättigheter).
#>
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
if ($PSVersionTable.PSEdition -ne 'Core') {
    [Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12
}
$Repo   = if ($env:UPPA_REPO)   { $env:UPPA_REPO }   else { 'pipebreak33/uppa' }
$Branch = if ($env:UPPA_BRANCH) { $env:UPPA_BRANCH } else { 'main' }
$OnWindows = ($PSVersionTable.PSEdition -ne 'Core') -or $IsWindows
$Dir = Join-Path $HOME '.uppa'
$PyVersion = '3.12.8'

function Say($m)  { Write-Host "  ▲ $m" -ForegroundColor Green }
function Warn($m) { Write-Host "  ! $m" -ForegroundColor Yellow }

function Update-SessionPath {
    if (-not $OnWindows) { return }
    $env:Path = (@([Environment]::GetEnvironmentVariable('Path', 'Machine'),
                   [Environment]::GetEnvironmentVariable('Path', 'User'),
                   (Join-Path $env:LOCALAPPDATA 'Microsoft\WindowsApps')) | Where-Object { $_ }) -join ';'
}

function Test-Python($exe, $extra) {
    try {
        & $exe @($extra + @('-c', 'import sys; sys.exit(sys.version_info < (3,8))')) 2>$null | Out-Null
        return ($LASTEXITCODE -eq 0)
    } catch { return $false }
}

function Find-Python {
    $candidates = if ($OnWindows) { @(@('py', '-3'), @('python'), @('python3')) } else { @(@('python3'), @('python')) }
    foreach ($c in $candidates) {
        $cmd = Get-Command $c[0] -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
        if (-not $cmd) { continue }
        $extra = @($c | Select-Object -Skip 1)
        # Microsoft Store-aliaset python.exe startar inget riktigt Python, Test-Python sorterar bort det
        if (Test-Python $cmd.Source $extra) { return , (@($cmd.Source) + $extra) }
    }
    if ($OnWindows) {
        foreach ($p in @("$env:LOCALAPPDATA\Programs\Python\Python312\python.exe",
                         "$env:LOCALAPPDATA\Programs\Python\Launcher\py.exe")) {
            if (Test-Path $p) {
                $extra = if ($p -like '*py.exe') { @('-3') } else { @() }
                if (Test-Python $p $extra) { return , (@($p) + $extra) }
            }
        }
    }
    return $null
}

function Install-Python {
    if (-not $OnWindows) {
        throw 'Python 3.8+ saknas. macOS: xcode-select --install (eller brew install python). Linux: sudo apt install python3.'
    }
    Update-SessionPath
    if (Get-Command winget -ErrorAction SilentlyContinue) {
        Say 'Installerar Python 3 med winget'
        winget install --id Python.Python.3.12 -e --scope user --silent --accept-package-agreements --accept-source-agreements
        if ($LASTEXITCODE -eq 0) { Update-SessionPath; return }
        Warn 'winget kunde inte installera Python, provar python.org'
    }
    $arch = switch ($env:PROCESSOR_ARCHITECTURE) { 'ARM64' { '-arm64' } 'x86' { '' } default { '-amd64' } }
    $url = "https://www.python.org/ftp/python/$PyVersion/python-$PyVersion$arch.exe"
    $exe = Join-Path $env:TEMP "python-$PyVersion-setup.exe"
    Say "Hämtar Python $PyVersion från python.org"
    Invoke-WebRequest $url -OutFile $exe -UseBasicParsing
    $p = Start-Process $exe -ArgumentList '/quiet', 'InstallAllUsers=0', 'PrependPath=1', 'Include_launcher=1',
                                         'Include_test=0', 'Shortcuts=0' -Wait -PassThru
    Remove-Item $exe -ErrorAction SilentlyContinue
    if ($p.ExitCode -ne 0 -and $p.ExitCode -ne 3010) { throw "Python-installationen misslyckades (kod $($p.ExitCode))." }
    Update-SessionPath
}

# 1. Python
$py = Find-Python
if (-not $py) {
    Install-Python
    $py = Find-Python
    if (-not $py) { throw 'Python installerades men syns inte än. Öppna ett NYTT PowerShell-fönster och kör installationen igen.' }
}

# 2. uppa.py (lokal kopia bredvid skriptet om den finns, annars från GitHub)
New-Item -ItemType Directory -Force -Path $Dir | Out-Null
$target = Join-Path $Dir 'uppa.py'
$local = if ($PSScriptRoot) { Join-Path $PSScriptRoot 'uppa.py' } else { $null }
if ($local -and (Test-Path $local) -and $env:UPPA_FROM_WEB -ne '1') {
    Say "Installerar från $PSScriptRoot"
    Copy-Item $local $target -Force
} else {
    Say "Hämtar uppa från github.com/$Repo ($Branch)"
    $tmp = "$target.new"
    Invoke-WebRequest "https://raw.githubusercontent.com/$Repo/$Branch/uppa.py" -OutFile $tmp -UseBasicParsing
    & $py[0] @(@($py | Select-Object -Skip 1) + @('-c', 'import ast,sys; ast.parse(open(sys.argv[1],encoding="utf-8").read())', $tmp))
    if ($LASTEXITCODE -ne 0) { throw 'Det nedladdade skriptet är trasigt.' }
    Move-Item $tmp $target -Force
}

# 3. Startkommando + PATH
if ($OnWindows) {
    $bin = Join-Path $Dir 'bin'
    New-Item -ItemType Directory -Force -Path $bin | Out-Null
    # Citera bara exe-filen: py-startaren skickar annars vidare ett citerat "-3" till python.exe
    $launcher = '"' + $py[0] + '"' + ((@($py | Select-Object -Skip 1) | ForEach-Object { " $_" }) -join '') +
                ' "%USERPROFILE%\.uppa\uppa.py" %*'
    Remove-Item (Join-Path $bin 'uppa.cmd') -Force -ErrorAction SilentlyContinue
    Set-Content -Path (Join-Path $bin 'uppa.cmd') -Value "@echo off`r`n$launcher" -Encoding ASCII
    $user = [Environment]::GetEnvironmentVariable('Path', 'User')
    if (-not $user) { $user = '' }
    if (($user -split ';') -notcontains $bin) {
        [Environment]::SetEnvironmentVariable('Path', (($user.TrimEnd(';') + ';' + $bin).TrimStart(';')), 'User')
        Say 'La till uppa i din PATH.'
    }
    if (($env:Path -split ';') -notcontains $bin) { $env:Path += ";$bin" }
} else {
    $bin = Join-Path $HOME '.local/bin'
    New-Item -ItemType Directory -Force -Path $bin | Out-Null
    $shim = Join-Path $bin 'uppa'
    Remove-Item $shim -Force -ErrorAction SilentlyContinue   # symlänk? skriv inte genom den
    Set-Content -Path $shim -Value "#!/usr/bin/env sh`nexec `"$($py[0])`" `"$target`" `"`$@`"`n" -NoNewline
    chmod +x $shim
    if ((($env:PATH -split ':') -notcontains $bin)) {
        Warn "Lägg till $bin i PATH (t.ex. i ~/.zshrc: export PATH=`"`$HOME/.local/bin:`$PATH`")"
    }
}

$ver = & $py[0] @(@($py | Select-Object -Skip 1) + @($target, '--version')) 2>$null
Write-Host "`n  ✔ $ver installerad. Öppna en ny terminal och kör: uppa   (grundpaketet: uppa install bas)`n" -ForegroundColor Green
if ($OnWindows -and -not (Get-Command winget -ErrorAction SilentlyContinue)) {
    Warn 'winget hittades inte. uppa behöver det för CLI-verktygen: uppdatera "App Installer" i Microsoft Store (https://aka.ms/getwinget).'
}
if (-not (Get-Command pwsh -ErrorAction SilentlyContinue)) {
    Warn 'PowerShell 7 (pwsh) saknas. Installera det med: uppa install powershell'
}
