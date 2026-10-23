param(
    [ValidateSet('2025','2026')][string]$RevitVersion = '2025',
    [string]$RevitPath = '',
    [ValidateSet('auto','net8.0-windows','net10.0-windows')][string]$Framework = 'auto',
    [switch]$SomenteCompilar
)
$ErrorActionPreference = 'Stop'
if (!$RevitPath) { $RevitPath = "C:\Program Files\Autodesk\Revit $RevitVersion" }
$api = Join-Path $RevitPath 'RevitAPI.dll'
if (!(Test-Path $api)) { throw "RevitAPI.dll não encontrada em $RevitPath" }
if (!(Get-Command dotnet -ErrorAction SilentlyContinue)) { throw 'Instale o SDK .NET 8 ou 10, conforme o Revit instalado, e reabra o PowerShell.' }
$version = [Diagnostics.FileVersionInfo]::GetVersionInfo($api)
if ($version.FileMajorPart -ne ([int]$RevitVersion - 2000)) { throw 'O caminho informado não corresponde ao ano escolhido.' }
if ($Framework -eq 'auto') {
    if ($version.FileMinorPart -ge 5) { $Framework = 'net10.0-windows' }
    else { $Framework = 'net8.0-windows' }
}
Write-Host "Revit API $($version.FileVersion) / $Framework" -ForegroundColor Cyan
$project = Join-Path $PSScriptRoot 'src\TOPOBIM.csproj'
$output = Join-Path $PSScriptRoot "build\$RevitVersion\$Framework"
# Um diretório intermediário por combinação evita reutilizar referências entre os anos.
$obj = Join-Path $PSScriptRoot "obj\$RevitVersion\$Framework\"
& dotnet build $project -c Release "-p:RevitVersion=$RevitVersion" "-p:RevitPath=$RevitPath" "-p:TargetFramework=$Framework" "-p:BaseIntermediateOutputPath=$obj" -o $output
if ($LASTEXITCODE -ne 0) { throw 'A compilação falhou. Nenhum manifesto será instalado.' }
if ($SomenteCompilar) { Write-Host "Compilado em $output"; exit 0 }
if (Get-Process Revit -ErrorAction SilentlyContinue) { throw 'Feche todas as instâncias do Revit e execute novamente para instalar.' }
$addins = Join-Path $env:APPDATA "Autodesk\Revit\Addins\$RevitVersion"
$destination = Join-Path $addins 'TopoBim'
$manifest = Join-Path $addins 'TOPOBIM.addin'
$legacyManifest = Join-Path $addins 'TopoStudio.addin'
if (Test-Path $legacyManifest) { Move-Item $legacyManifest "$legacyManifest.disabled-$(Get-Date -Format yyyyMMddHHmmss)" }

if (Test-Path $manifest) {
    $backup = "$manifest.backup-$(Get-Date -Format yyyyMMddHHmmss)"
    Copy-Item $manifest $backup
}
New-Item -ItemType Directory -Force -Path $destination | Out-Null
Copy-Item (Join-Path $output '*') $destination -Force -Recurse
$assembly = [Security.SecurityElement]::Escape((Join-Path $destination 'TOPOBIM.dll'))
@"
<?xml version="1.0" encoding="utf-8"?>
<RevitAddIns>
  <AddIn Type="Application">
    <Name>TOPOBIM</Name>
    <Assembly>$assembly</Assembly>
    <AddInId>D4D1C2A4-7913-4EA3-9CC9-9FE7B303227A</AddInId>
    <FullClassName>TopoBim.App</FullClassName>
    <VendorId>JVTP</VendorId>
    <VendorDescription>TOPOBIM - Arquitetura e BIM</VendorDescription>
  </AddIn>
</RevitAddIns>
"@ | Set-Content $manifest -Encoding UTF8
Write-Host "Instalado para Revit $RevitVersion. Abra o Revit e acesse TOPOBIM > Criar terreno." -ForegroundColor Green
