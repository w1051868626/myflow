[CmdletBinding()]
param(
    [string]$VersionRoot = 'D:\Programs\nvm\installs',
    [string]$Version = '24.19.0'
)

$ErrorActionPreference = 'Stop'
$VersionRoot = [System.IO.Path]::GetFullPath($VersionRoot)
$runtimePath = Join-Path $VersionRoot "v$Version"
$runtimeNode = Join-Path $runtimePath 'node.exe'
if (!(Test-Path -LiteralPath $runtimeNode)) {
    throw "Installed Node.js was not found at $runtimeNode. No settings have been changed."
}
$actualVersion = (& $runtimeNode --version).Trim()
if ($LASTEXITCODE -ne 0 -or $actualVersion -ne "v$Version") {
    throw "Unexpected Node.js version at $runtimeNode : $actualVersion"
}

$nvmCommand = Get-Command nvm.exe -CommandType Application -ErrorAction SilentlyContinue
if ($nvmCommand) {
    $nvmExecutable = $nvmCommand.Source
} else {
    $nvmExecutable = Join-Path $env:LOCALAPPDATA 'Author Software\nvm\nvm.exe'
}
if (!(Test-Path -LiteralPath $nvmExecutable)) {
    throw 'nvm.exe was not found. Open a terminal where nvm is available and run this script again.'
}

function Invoke-LocalNvm {
    param([string[]]$Arguments)
    & $nvmExecutable @Arguments | Out-Host
    if ($LASTEXITCODE -ne 0) {
        throw "nvm $($Arguments -join ' ') failed."
    }
}

Write-Host "NVM executable: $nvmExecutable"
$settingsJson = & $nvmExecutable config get root mode --json
if ($LASTEXITCODE -ne 0) { throw 'Unable to read nvm settings.' }
$settings = $settingsJson | ConvertFrom-Json
Write-Host "Current version directory: $($settings.root)"

# This must run inside the same terminal/user context that will use nvm.
# Avoid setting unchanged values: this nvm beta reports them as errors.
if ($settings.root.TrimEnd('\', '/') -ine $VersionRoot.TrimEnd('\', '/')) {
    Invoke-LocalNvm -Arguments @('config', 'set', "root=$VersionRoot")
}
if ($settings.mode -ne 'link') {
    Invoke-LocalNvm -Arguments @('use', 'link')
}

# --local with a major version bypasses the online version manifest.
$majorVersion = $Version.Split('.')[0]
Invoke-LocalNvm -Arguments @('use', $majorVersion, '--local')
Invoke-LocalNvm -Arguments @('on')

$managedEntry = Join-Path ([System.IO.Path]::GetDirectoryName($VersionRoot)) '.link\nodejs'
foreach ($commandFile in @('node.exe', 'npm.cmd', 'pnpm.cmd')) {
    if (!(Test-Path -LiteralPath (Join-Path $managedEntry $commandFile))) {
        throw "Missing $commandFile in $managedEntry. PATH has not been changed."
    }
}
$selectedVersion = (& (Join-Path $managedEntry 'node.exe') --version).Trim()
if ($selectedVersion -ne "v$Version") {
    throw "nvm selected $selectedVersion instead of v$Version. PATH has not been changed."
}

# Keep other PATH entries and Conda activation intact. Replace only nvm's
# outdated shim entry with the link maintained by nvm in the configured root.
$nvmDirectory = Split-Path -Parent $nvmExecutable
$oldShimEntry = Join-Path $nvmDirectory '.nodejs'
function Keep-OtherPathEntries {
    param([string]$Value)
    $Value -split ';' | Where-Object {
        $_ -and $_.TrimEnd('\', '/') -ine $oldShimEntry.TrimEnd('\', '/') -and
        $_.TrimEnd('\', '/') -ine $managedEntry.TrimEnd('\', '/')
    }
}
$currentUserPath = [System.Environment]::GetEnvironmentVariable('Path', 'User')
$otherUserEntries = @(Keep-OtherPathEntries -Value $currentUserPath)
$newUserPath = (@($managedEntry) + $otherUserEntries) -join ';'
if ($newUserPath -ne $currentUserPath) {
    [System.Environment]::SetEnvironmentVariable('Path', $newUserPath, 'User')
}
$env:Path = (@($managedEntry) + @(Keep-OtherPathEntries -Value $env:Path)) -join ';'

Write-Host "`nConfigured in this terminal:"
Invoke-LocalNvm -Arguments @('config', 'get', 'root', 'mode', '--json')
Invoke-LocalNvm -Arguments @('list')
foreach ($commandFile in @('node.exe', 'npm.cmd', 'pnpm.cmd')) {
    & (Join-Path $managedEntry $commandFile) --version
    if ($LASTEXITCODE -ne 0) { throw "$commandFile verification failed." }
}
Write-Host "`nDone. Restart other terminals/editors to refresh their PATH."
