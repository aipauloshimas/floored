# what Claude does on a creator's Windows computer by SKILL.md, steps 2 to 8. Windows PowerShell 5.1.
$ErrorActionPreference = 'Continue'
$ProgressPreference = 'SilentlyContinue'
$repo = (Get-Location).Path
$work = Join-Path $env:RUNNER_TEMP 'fc'
New-Item -ItemType Directory -Force $work | Out-Null
$app = Join-Path $repo 'plugin\skills\floored\app'
$check = Join-Path $repo '.github\first-contact\fc_check.py'
$fhome = Join-Path $env:USERPROFILE '.floored'
function Ok($step, $t) { "FC ok $step $([int]((Get-Date) - $t).TotalSeconds)s" }
function Die($m) { "FC FAIL $m"; exit 1 }
function Finder($extra) {
  $a = @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', (Join-Path $app 'get-python.ps1'))
  if ($extra) { $a += $extra }
  $o = & powershell @a 2> (Join-Path $work 'finder.err')
  $script:rc = $LASTEXITCODE
  Write-Host "stderr: $(Get-Content (Join-Path $work 'finder.err') -Raw)"
  return (@($o) -join "`n").Trim()
}
function Dr($name, $a) {
  # runs floored.py <a...> with PY; stdout to $work\$name.out, stderr to $name.err; exit code in $script:rc.
  # cmd does the redirection: PowerShell 5.1 would write UTF-16, and a pipe would stay open while the studio runs.
  $q = (@($script:PY, (Join-Path $app 'floored.py')) + $a | ForEach-Object { '"' + $_ + '"' }) -join ' '
  $o = Join-Path $work "$name.out"; $e = Join-Path $work "$name.err"
  $bat = Join-Path $work "$name.cmd"
  Set-Content -Path $bat -Encoding ascii -Value "@$q > `"$o`" 2> `"$e`""
  & cmd /c $bat
  $script:rc = $LASTEXITCODE
}
function Tail($f, $n) { if (Test-Path $f) { Get-Content $f | Select-Object -Last $n } }

# 2 the finder
$t = Get-Date
$o = Finder $null
"stdout: [$o] exit $rc"
if ($rc -ne 3 -or $o -ne 'NO_PYTHON') { Die "finder: expected NO_PYTHON exit 3" }
Ok 'finder-no-python' $t

# 3 --install
$t = Get-Date
$o = Finder '--install'
"stdout: [$o] exit $rc"
$under = Join-Path $fhome 'tools\python'
if ($rc -ne 0 -or $o -notmatch '^FLOORED_PYTHON=' -or $o.Contains("`n") -or -not $o.StartsWith("FLOORED_PYTHON=$under")) { Die "finder --install: unexpected output" }
$script:PY = $o.Substring('FLOORED_PYTHON='.Length)
$PY = $script:PY
Ok 'finder-install' $t
$t = Get-Date
$o2 = Finder $null
"stdout: [$o2] exit $rc"
if ($rc -ne 0 -or $o2 -ne $o) { Die "finder again: not the same path" }
Ok 'finder-again' $t
"PY=$PY"

# 4 doctor before
$t = Get-Date
Dr 'doctor-before' @('doctor', '--json')
"doctor exit $rc"
Tail (Join-Path $work 'doctor-before.err') 20
if ($rc -ne 1) { Die "doctor --json expected exit 1, got $rc" }
& $PY $check before (Join-Path $work 'doctor-before.out'); if ($LASTEXITCODE -ne 0) { Die 'doctor items before' }
Ok 'doctor-before' $t

# 5 installs
foreach ($item in 'node', 'ffmpeg', 'venv', 'packages', 'rvm-model', 'renderer', 'words') {
  $t = Get-Date
  Dr "install-$item" @('doctor', '--install', $item)
  "--- $item exit $rc"
  Tail (Join-Path $work "install-$item.out") 5
  "stderr tail:"; Tail (Join-Path $work "install-$item.err") 8
  if ($rc -ne 0) { Die "doctor --install $item exit $rc" }
  & $PY $check installed (Join-Path $work "install-$item.out"); if ($LASTEXITCODE -ne 0) { Die "install $item not ok" }
  Ok "install-$item" $t
}

# 6 doctor after, gpu check
$t = Get-Date
Dr 'doctor-after' @('doctor', '--json')
"doctor exit $rc"
if ($rc -ne 0) { Tail (Join-Path $work 'doctor-after.out') 60; Die "doctor --json after expected exit 0, got $rc" }
& $PY $check after (Join-Path $work 'doctor-after.out'); if ($LASTEXITCODE -ne 0) { Die 'doctor items after' }
Ok 'doctor-after' $t
$t = Get-Date
Dr 'gpu' @('doctor', '--gpu-check')
"gpu-check exit $rc (does not fail the job)"
Tail (Join-Path $work 'gpu.out') 15; Tail (Join-Path $work 'gpu.err') 15
Ok 'gpu-check' $t

# 7 the product flow
$t = Get-Date
$ws = Join-Path $work 'ws'
New-Item -ItemType Directory -Force $ws | Out-Null
Dr 'add' @('add', '--workspace', $ws, (Join-Path $app 'sample\source.mp4'))
"add exit $rc"; Tail (Join-Path $work 'add.out') 10; Tail (Join-Path $work 'add.err') 10
if ($rc -ne 0) { Die "add exit $rc" }
$take = (& $PY $check take (Join-Path $work 'add.out')) -join ''
$take = $take.Trim()
"take: $take"
Ok 'add' $t
$t = Get-Date
Dr 'wait' @('wait', '--workspace', $ws, '--take', $take, '--timeout', '1800')
"wait exit $rc"; Tail (Join-Path $work 'wait.out') 10; Tail (Join-Path $work 'wait.err') 10
if ($rc -ne 0) { Die "wait exit $rc" }
Ok 'wait' $t
$t = Get-Date
Dr 'status1' @('status', '--workspace', $ws)
"status (running):"; Tail (Join-Path $work 'status1.out') 40
$s1 = (Get-Content (Join-Path $work 'status1.out') -Raw)
if ($rc -ne 0) { Die 'status exit' }
& $PY $check running (Join-Path $work 'status1.out') $take; if ($LASTEXITCODE -ne 0) { Die 'status while running' }
Dr 'stop' @('stop', '--workspace', $ws)
"stop exit $rc"; Tail (Join-Path $work 'stop.out') 10
if ($rc -ne 0) { Die "stop exit $rc" }
Start-Sleep -Seconds 3
Dr 'status2' @('status', '--workspace', $ws)
"status (stopped):"; Tail (Join-Path $work 'status2.out') 40
$s2 = (Get-Content (Join-Path $work 'status2.out') -Raw)
& $PY $check stopped (Join-Path $work 'status2.out') $take; if ($LASTEXITCODE -ne 0) { Die 'status after stop' }
$wsTake = Get-ChildItem -Recurse -Force $ws -Filter $take -ErrorAction SilentlyContinue | Select-Object -First 1
"take on disk: $($wsTake.FullName)"
if (-not $wsTake) { Die 'the take is gone from the workspace' }
Ok 'status-stop' $t

# 8 sizes
function Size($p) { if (Test-Path $p) { $s = (Get-ChildItem $p -Recurse -Force -File -ErrorAction SilentlyContinue | Measure-Object Length -Sum).Sum; "SIZE $p $([math]::Round($s/1MB,1)) MB" } else { "SIZE $p absent" } }
foreach ($d in 'tools\python', 'tools\node', 'tools\ffmpeg', 'venv', 'renderer', '') { Size (Join-Path $fhome $d) }
Ok 'sizes' (Get-Date)
exit 0
