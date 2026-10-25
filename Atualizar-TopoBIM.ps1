param(
    [string]$InstalledExtension = "$env:APPDATA/pyRevit/Extensions/OmniBIM.extension.extension"
)
$ErrorActionPreference = 'Stop'
$relativeButton = 'OmniBIM.tab/Utilitários.panel/topobim.pushbutton'
$sourceButton = Join-Path $PSScriptRoot $relativeButton
$destinationButton = Join-Path $InstalledExtension $relativeButton
if (!(Test-Path -LiteralPath (Join-Path $destinationButton 'script.py'))) {
    throw "Botão instalado não encontrado em $destinationButton. Informe -InstalledExtension com a extensão carregada pelo pyRevit."
}
$sourcePath = (Resolve-Path -LiteralPath $sourceButton).Path
$destinationPath = (Resolve-Path -LiteralPath $destinationButton).Path
if ($sourcePath -eq $destinationPath) {
    Write-Host 'O pyRevit já está usando esta pasta de código.'
    return
}
# Update only this button's runtime files; retain an independent backup.
$runtimeFiles = @('script.py', 'bundle.yaml', 'TopoBim.xaml', 'Occurrences.xaml',
                  'TopoBimTheme.xaml',
                  'topobim_core.py', 'topobim_geo.py', 'topobim_revit.py', 'topobim_ui.py',
                  'topobim_floor_geometry.py', 'topobim_floors.py', 'topobim_preview.py', 'topobim_view3d.py',
                  'topobim_measure.py', 'topobim_measure_ui.py',
                  'icon.png', 'icon.dark.png', 'README.md')
foreach ($fileName in $runtimeFiles) {
    if (!(Test-Path -LiteralPath (Join-Path $sourcePath $fileName))) {
        throw "Arquivo de origem ausente: $fileName"
    }
}
$backupPath = Join-Path $env:LOCALAPPDATA ('OmniBIM/backups/topobim-' + (Get-Date -Format 'yyyyMMdd-HHmmss-ffff'))
[void](New-Item -ItemType Directory -Path $backupPath -Force)
foreach ($fileName in $runtimeFiles) {
    $installedFile = Join-Path $destinationPath $fileName
    if (Test-Path -LiteralPath $installedFile) {
        Copy-Item -LiteralPath $installedFile -Destination (Join-Path $backupPath $fileName)
    }
}
foreach ($fileName in $runtimeFiles) {
    $sourceFile = Join-Path $sourcePath $fileName
    $installedFile = Join-Path $destinationPath $fileName
    Copy-Item -LiteralPath $sourceFile -Destination $installedFile -Force
    if ((Get-FileHash -LiteralPath $sourceFile -Algorithm SHA256).Hash -ne
        (Get-FileHash -LiteralPath $installedFile -Algorithm SHA256).Hash) {
        throw "A verificação da cópia falhou: $fileName. Backup em $backupPath"
    }
}
Write-Host "TOPOBIM atualizado em: $destinationPath"
Write-Host "Backup da instalação anterior: $backupPath"
Write-Host 'Feche a janela TOPOBIM se estiver aberta e abra o botão novamente. Use Reload do pyRevit para atualizar os metadados do botão.'
