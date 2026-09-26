$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
$userPath = [Environment]::GetEnvironmentVariable("Path", "User")
$pathEntries = @($userPath -split ";" | Where-Object { $_ })

if (-not ($pathEntries | Where-Object { $_.TrimEnd("\") -ieq $projectRoot.TrimEnd("\") })) {
    $updatedPath = if ($userPath) { "$userPath;$projectRoot" } else { $projectRoot }
    [Environment]::SetEnvironmentVariable("Path", $updatedPath, "User")
}

Write-Host "Comando tethys instalado para novas janelas do PowerShell."
Write-Host "Feche e reabra o PowerShell; depois use: tethys --dev"
