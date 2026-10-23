param([ValidateSet('2025','2026')][string]$RevitVersion = '2025')
$ErrorActionPreference = 'Stop'
if (Get-Process Revit -ErrorAction SilentlyContinue) { throw 'Feche o Revit antes de desinstalar.' }
$addins = Join-Path $env:APPDATA "Autodesk\Revit\Addins\$RevitVersion"
$manifest = Join-Path $addins 'TOPOBIM.addin'
if (Test-Path $manifest) { Remove-Item $manifest }
# Desativa o plugin. As DLLs ficam preservadas para evitar excluir arquivos do usuário.
Write-Host "TOPOBIM desativado para Revit $RevitVersion. Modelos RVT não foram alterados."
