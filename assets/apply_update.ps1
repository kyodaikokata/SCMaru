$ErrorActionPreference = 'Stop'
$stage = [IO.Path]::GetFullPath($env:SCMARU_UPDATE_STAGE)
$install = [IO.Path]::GetDirectoryName($stage)
if ($stage -ne $PSScriptRoot -or $install -ne (Get-Location).ProviderPath -or
    [IO.Path]::GetFileName($stage) -notlike '.scmaru-update-*' -or
    ((Get-Item -LiteralPath $stage -Force).Attributes -band [IO.FileAttributes]::ReparsePoint)) {
    throw 'Invalid update staging directory'
}

$names = @('SCMaru.exe', '_internal', 'VERSION.txt', 'README.md', 'CHANGELOG.md',
    'IDENTITY_CODE_GUIDE.md', 'LIVEHIME.md', 'FONT_LICENSES.txt', 'THIRD_PARTY_LICENSES.txt')
$incoming = Join-Path $stage 'SCMaru'
$backup = Join-Path $stage 'backup'
$previous = [Collections.Generic.List[string]]::new()
$installed = [Collections.Generic.List[string]]::new()
try {
    $parent = Get-Process -Id ([int]$env:SCMARU_UPDATE_PID) -ErrorAction SilentlyContinue
    if ($parent -and !$parent.WaitForExit(30000)) {
        throw 'SCMaru is still running'
    }
    foreach ($name in $names) {
        $old = Join-Path $install $name
        if (!(Test-Path -LiteralPath $old)) { continue }
        $item = Get-Item -LiteralPath $old -Force
        if (($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -or
            ($item.PSIsContainer -and $name -ne '_internal')) {
            throw "Unexpected program file: $name"
        }
        if ($item.PSIsContainer) {
            $linked = Get-ChildItem -LiteralPath $old -Recurse -Force |
                Where-Object { $_.Attributes -band [IO.FileAttributes]::ReparsePoint } |
                Select-Object -First 1
            if ($linked) { throw "Linked item inside $name" }
        }
    }
    New-Item -ItemType Directory -Path $backup | Out-Null
    foreach ($name in $names) {
        $old = Join-Path $install $name
        if (Test-Path -LiteralPath $old) {
            Move-Item -LiteralPath $old -Destination $backup
            $previous.Add($name)
        }
    }
    foreach ($name in $names) {
        $new = Join-Path $incoming $name
        if (Test-Path -LiteralPath $new) {
            Move-Item -LiteralPath $new -Destination $install
            $installed.Add($name)
        }
    }
    Start-Process -FilePath (Join-Path $install 'SCMaru.exe') -ArgumentList $env:SCMARU_UPDATE_ARGS -WorkingDirectory $install
} catch {
    $failure = $_
    try {
        foreach ($name in $installed) {
            Move-Item -LiteralPath (Join-Path $install $name) -Destination $incoming
        }
        foreach ($name in $previous) {
            Move-Item -LiteralPath (Join-Path $backup $name) -Destination $install
        }
    } catch {
        $failure = "$failure`n$_"
    }
    Add-Type -AssemblyName System.Windows.Forms
    [void][Windows.Forms.MessageBox]::Show("$env:SCMARU_UPDATE_FAILURE`n$failure`n$stage", 'SCMaru')
    exit 1
}

Remove-Item -LiteralPath $stage -Recurse -Force
