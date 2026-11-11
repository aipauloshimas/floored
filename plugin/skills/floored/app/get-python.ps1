# get-python.ps1 - find a Python 3.10 or newer on Windows, or download floored's own copy.
#
#   get-python.ps1            prints  FLOORED_PYTHON=<full path>  (exit 0), or  NO_PYTHON  (exit 3)
#   get-python.ps1 --install  downloads floored's own Python into <home>\tools\python (only what tools.txt pins),
#                             then prints  FLOORED_PYTHON=<full path>  (exit 0); a failure is one sentence on stderr (exit 1)
#
# <home> is $env:FLOORED_HOME, else .floored in the user's home folder. Nothing is written outside <home>\tools:
# no admin rights, no PATH change, no registry. Written for Windows PowerShell 5.1.
# Call it as: powershell -NoProfile -ExecutionPolicy Bypass -File get-python.ps1 [--install]

$ErrorActionPreference = 'Continue'
$ProgressPreference = 'SilentlyContinue'
# The one line this script prints is a path, and a home folder can hold accents: print it as UTF-8, which is what
# Claude's shell reads. (With no console attached the default stays.)
try { [Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false) } catch { }

function Say([string]$text) { [Console]::Out.WriteLine($text) }
function Note([string]$text) { [Console]::Error.WriteLine($text) }

function Get-Home {
    if ($env:FLOORED_HOME) { return $env:FLOORED_HOME }
    return (Join-Path ([Environment]::GetFolderPath('UserProfile')) '.floored')
}

# A candidate counts only when running it proves it is Python 3.10 or newer. The Microsoft Store stub answers
# with an error code when it gets arguments, so it fails here.
function Test-Python([string]$exe) {
    if (-not $exe) { return $false }
    if (-not (Test-Path -LiteralPath $exe -PathType Leaf)) { return $false }
    try {
        $null = & $exe -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)" 2>&1
        return ($LASTEXITCODE -eq 0)
    } catch {
        return $false
    }
}

function Get-OwnPython { return (Join-Path (Join-Path (Join-Path (Get-Home) 'tools') 'python') 'python.exe') }

function Find-Python {
    $own = Get-OwnPython
    if (Test-Python $own) { return (Resolve-Path -LiteralPath $own).ProviderPath }

    # python on PATH (every match, so a stub earlier on PATH does not hide a real one after it)
    $found = @(Get-Command python -CommandType Application -All -ErrorAction SilentlyContinue)
    foreach ($c in $found) {
        if (Test-Python $c.Path) { return $c.Path }
    }

    # the py launcher: print the program it resolves to
    $launcher = Get-Command py -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($launcher) {
        try {
            $out = & $launcher.Path -3 -c "import sys; print(sys.executable)" 2>&1
            if ($LASTEXITCODE -eq 0) {
                $line = (@($out) | Where-Object { $_ -is [string] } | Select-Object -First 1)
                if ($line -and (Test-Python $line.Trim())) { return $line.Trim() }
            }
        } catch { }
    }

    # the python.org installer's default place, newest first
    if ($env:LOCALAPPDATA) {
        $root = Join-Path $env:LOCALAPPDATA 'Programs\Python'
        if (Test-Path -LiteralPath $root -PathType Container) {
            $dirs = @(Get-ChildItem -LiteralPath $root -Directory -Filter 'Python3*' -ErrorAction SilentlyContinue)
            $dirs = $dirs | Sort-Object { $n = ($_.Name -replace '\D', ''); if ($n.Length -gt 1) { [int]$n.Substring(1) } else { 0 } } -Descending
            foreach ($d in $dirs) {
                $exe = Join-Path $d.FullName 'python.exe'
                if (Test-Python $exe) { return $exe }
            }
        }
    }
    return $null
}

function Remove-Quietly([string]$path) {
    if (Test-Path -LiteralPath $path) {
        Remove-Item -LiteralPath $path -Recurse -Force -ErrorAction SilentlyContinue
    }
}

function Fail([string]$sentence) {
    $tools = Join-Path (Get-Home) 'tools'
    Remove-Quietly (Join-Path $tools 'python.part')
    Remove-Quietly (Join-Path $tools 'python.new')
    Remove-Quietly (Join-Path $tools 'python')
    Note $sentence
    exit 1
}

function Install-Python {
    $existing = Find-Own
    if ($existing) { Say ('FLOORED_PYTHON=' + $existing); exit 0 }

    $tools = Join-Path (Get-Home) 'tools'
    $part = Join-Path $tools 'python.part'
    $new = Join-Path $tools 'python.new'
    $dest = Join-Path $tools 'python'

    # a broken leftover is replaced
    Remove-Quietly $dest

    $pins = $env:FLOORED_TOOLS_FILE
    if (-not $pins) { $pins = Join-Path $PSScriptRoot 'tools.txt' }
    $line = $null
    if (Test-Path -LiteralPath $pins -PathType Leaf) {
        foreach ($raw in (Get-Content -LiteralPath $pins)) {
            $t = $raw.Trim()
            if ($t -eq '' -or $t.StartsWith('#')) { continue }
            $f = $t -split '\s+'
            if ($f.Count -ge 5 -and $f[0] -eq 'python' -and $f[1] -eq 'win-x64') { $line = $f; break }
        }
    }
    if (-not $line) { Fail "This computer's system has no Python download in floored's list." }
    $size = [int64]$line[2]
    $sha = $line[3].ToLowerInvariant()
    $url = $line[4]

    try {
        New-Item -ItemType Directory -Force -Path $tools | Out-Null
        Remove-Quietly $part
        Remove-Quietly $new
        try {
            [Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12
        } catch { }
        Note 'Downloading Python for floored...'
        try {
            Invoke-WebRequest -UseBasicParsing -Uri $url -OutFile $part -ErrorAction Stop
        } catch {
            $reason = ($_.Exception.Message -replace '\s+', ' ').Trim()
            Fail ("Couldn't download Python (" + $reason + "). Check the internet connection and try again.")
        }
        $got = (Get-Item -LiteralPath $part).Length
        $hash = (Get-FileHash -LiteralPath $part -Algorithm SHA256).Hash.ToLowerInvariant()
        if ($got -ne $size -or $hash -ne $sha) {
            Fail "The Python download didn't match the expected file, so it was thrown away. Try again."
        }

        New-Item -ItemType Directory -Force -Path $new | Out-Null
        # tar gets names only, from inside the tools folder: a home folder with accents never passes through its arguments
        $tar = Join-Path $env:SystemRoot 'System32\tar.exe'
        Push-Location -LiteralPath $tools
        try {
            $null = & $tar -xzf 'python.part' -C 'python.new' 2>&1
            $tarCode = $LASTEXITCODE
        } finally {
            Pop-Location
        }
        if ($tarCode -ne 0 -or -not (Test-Path -LiteralPath (Join-Path $new 'python') -PathType Container)) {
            Fail "Couldn't download Python (the file could not be unpacked). Check the internet connection and try again."
        }
        Move-Item -LiteralPath (Join-Path $new 'python') -Destination $dest -Force
        Remove-Quietly $new
        Remove-Quietly $part

        $exe = Get-OwnPython
        if (-not (Test-Python $exe)) {
            Fail "Couldn't download Python (the new copy did not start). Check the internet connection and try again."
        }
        Say ('FLOORED_PYTHON=' + (Resolve-Path -LiteralPath $exe).ProviderPath)
        exit 0
    } catch {
        $reason = ($_.Exception.Message -replace '\s+', ' ').Trim()
        Fail ("Couldn't download Python (" + $reason + "). Check the internet connection and try again.")
    }
}

function Find-Own {
    $own = Get-OwnPython
    if (Test-Python $own) { return (Resolve-Path -LiteralPath $own).ProviderPath }
    return $null
}

if ($args -contains '--install') {
    Install-Python
} else {
    $py = Find-Python
    if ($py) { Say ('FLOORED_PYTHON=' + $py); exit 0 }
    Say 'NO_PYTHON'
    exit 3
}
