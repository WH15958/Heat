[CmdletBinding()]
param(
    [string]$Python = 'python',
    [Parameter(Mandatory = $true)][string]$ISCC,
    [Parameter(Mandatory = $true)][string]$WebView2Installer,
    [switch]$SkipFrontend,
    [switch]$SkipDependencyInstall
)

$ErrorActionPreference = 'Stop'
$desktopRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$desktopBuild = Join-Path $desktopRoot 'output\desktop'
$desktopEnvironment = Join-Path $desktopBuild 'venv'
$desktopPython = Join-Path $desktopEnvironment 'Scripts\python.exe'
$desktopCompiler = (Resolve-Path -LiteralPath $ISCC).Path
$desktopRuntimeSource = (Resolve-Path -LiteralPath $WebView2Installer).Path

function Invoke-Checked {
    param([string]$Executable, [string[]]$Arguments)
    & $Executable @Arguments
    if ($LASTEXITCODE -ne 0) { throw "$Executable failed with exit code $LASTEXITCODE" }
}

# Refuse a bootstrapper: the release must be usable without network access.
$desktopRuntimeInfo = Get-Item -LiteralPath $desktopRuntimeSource
$desktopSignature = Get-AuthenticodeSignature -LiteralPath $desktopRuntimeSource
if (($desktopSignature.Status -ne 'Valid') -or
    ($desktopSignature.SignerCertificate.Subject -notmatch 'O=Microsoft Corporation(?:,|$)') -or
    ($desktopRuntimeInfo.VersionInfo.ProductName -ne 'Microsoft Edge Update') -or
    ($desktopRuntimeInfo.VersionInfo.OriginalFilename -ne 'MicrosoftEdgeUpdateSetup.exe') -or
    ($desktopRuntimeInfo.Name -ne 'MicrosoftEdgeWebView2RuntimeInstallerX64.exe') -or
    ($desktopRuntimeInfo.Length -lt 80MB)) {
    throw 'Supply the signed Microsoft Evergreen Standalone x64 installer, not the network bootstrapper.'
}

Invoke-Checked $Python @('-c', 'import sys,struct; assert sys.version_info[:2] == (3,10) and struct.calcsize("P") == 8, "Desktop builds require Python 3.10 x64"')
New-Item -ItemType Directory -Force -Path $desktopBuild | Out-Null
if (-not (Test-Path -LiteralPath $desktopPython)) {
    Invoke-Checked $Python @('-m', 'venv', $desktopEnvironment)
}
Invoke-Checked $desktopPython @('-c', 'import sys,struct; assert sys.version_info[:2] == (3,10) and struct.calcsize("P") == 8, "The desktop venv must be Python 3.10 x64"')
if (-not $SkipDependencyInstall) {
    Invoke-Checked $desktopPython @('-m', 'pip', 'install', '-r', (Join-Path $desktopRoot 'requirements-desktop-build.txt'))
}
Invoke-Checked $desktopPython @('-m', 'pip', 'check')
Invoke-Checked $desktopPython @('-c', 'import PyInstaller, webview, pystray, psutil, win32api, win32file, win32security, resvg_py')

Push-Location $desktopRoot
try {
    if (-not $SkipFrontend) {
        Push-Location (Join-Path $desktopRoot 'frontend')
        try {
            Invoke-Checked 'npm.cmd' @('ci')
            Invoke-Checked 'npm.cmd' @('run', 'build', '--', '--mode', 'production')
        } finally { Pop-Location }
    }
    if (-not (Test-Path -LiteralPath 'src\web\static\index.html')) { throw 'Production frontend is missing.' }
    $desktopIcon = Join-Path $desktopBuild 'assets\heat.ico'
    Invoke-Checked $desktopPython @('packaging\desktop\make_icon.py', $desktopIcon)
    $desktopPreviousIcon = $env:HEAT_BUILD_ICON
    try {
        $env:HEAT_BUILD_ICON = $desktopIcon
        Invoke-Checked $desktopPython @('-m', 'PyInstaller', '--noconfirm', '--clean', '--distpath',
            (Join-Path $desktopBuild 'dist'), '--workpath', (Join-Path $desktopBuild 'build'), 'packaging\desktop\heat.spec')
    } finally { $env:HEAT_BUILD_ICON = $desktopPreviousIcon }

    $desktopRuntime = Join-Path $desktopBuild 'runtime\MicrosoftEdgeWebView2RuntimeInstallerX64.exe'
    New-Item -ItemType Directory -Force -Path (Split-Path $desktopRuntime) | Out-Null
    if ($desktopRuntimeSource -ne $desktopRuntime) { Copy-Item -LiteralPath $desktopRuntimeSource -Destination $desktopRuntime -Force }
    $desktopVersion = (& $desktopPython -c 'from src.desktop.common import VERSION; print(VERSION)').Trim()
    if ($LASTEXITCODE -ne 0 -or $desktopVersion -notmatch '^\d+\.\d+\.\d+$') { throw 'Invalid desktop VERSION.' }
    Invoke-Checked $desktopCompiler @("/DBuildRoot=$desktopBuild", "/DWebView2Installer=$desktopRuntime",
        "/DAppVersion=$desktopVersion", 'packaging\desktop\heat.iss')
    Invoke-Checked $desktopPython @('packaging\desktop\verify_bundle.py', $desktopBuild, '--version', $desktopVersion,
        '--runtime', $desktopRuntime, '--iscc', $desktopCompiler)
    Write-Host "Desktop installer and manifest: $desktopBuild"
} finally { Pop-Location }
