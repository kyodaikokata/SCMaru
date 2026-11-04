param([switch]$Demo)
$ErrorActionPreference = 'Stop'
$scdeskPython = Join-Path $PSScriptRoot '.venv\Scripts\pythonw.exe'
if (-not (Test-Path -LiteralPath $scdeskPython)) {
    throw 'Python environment missing. See README.md for installation instructions.'
}
$scdeskArgs = @((Join-Path $PSScriptRoot 'app.py'))
if ($Demo) { $scdeskArgs += '--demo' }
& $scdeskPython @scdeskArgs
