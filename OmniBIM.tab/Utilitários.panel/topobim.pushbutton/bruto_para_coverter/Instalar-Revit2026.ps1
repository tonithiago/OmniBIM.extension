$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
try {
    if (Get-Process Revit -ErrorAction SilentlyContinue) { throw 'Feche o Revit antes de instalar.' }
    $revitPath = 'C:\Program Files\Autodesk\Revit 2026'
    if (!(Test-Path -LiteralPath (Join-Path $revitPath 'RevitAPI.dll'))) {
        $revitPath = Read-Host 'Informe a pasta onde o Revit 2026 esta instalado'
    }
    $api = Join-Path $revitPath 'RevitAPI.dll'
    if (!(Test-Path -LiteralPath $api)) { throw 'RevitAPI.dll nao encontrada.' }
    if (([Diagnostics.FileVersionInfo]::GetVersionInfo($api)).FileMajorPart -ne 26) { throw 'A pasta nao corresponde ao Revit 2026.' }
    $config = Join-Path $revitPath 'RevitAPI.runtimeconfig.json'
    if (!(Test-Path -LiteralPath $config)) { throw 'Nao foi possivel identificar o .NET do Revit. Envie o registro de instalacao ao responsavel pelo plugin.' }
    $runtime = (Get-Content -LiteralPath $config -Raw | ConvertFrom-Json).runtimeOptions.tfm
    if ($runtime -notmatch '^net(8|10)\.0$') { throw "Runtime nao suportado neste pacote: $runtime" }
    $major = $Matches[1]
    $framework = "net$major.0-windows"
    $toolDir = Join-Path $PSScriptRoot '.tools'
    $sdkDir = Join-Path $toolDir "dotnet-$major"
    $cli = Join-Path $sdkDir 'dotnet.exe'
    New-Item -ItemType Directory -Force -Path $toolDir | Out-Null
    if (!(Test-Path -LiteralPath $cli)) {
        Write-Host "Baixando SDK .NET $major oficial da Microsoft. Aguarde..."
        [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
        $installer = Join-Path $toolDir 'dotnet-install.ps1'
        Invoke-WebRequest 'https://dot.net/v1/dotnet-install.ps1' -OutFile $installer -UseBasicParsing
        & $installer -Channel "$major.0" -InstallDir $sdkDir -NoPath
        if (!(Test-Path -LiteralPath $cli)) { throw 'O download do SDK nao foi concluido.' }
    }
    $env:DOTNET_ROOT = $sdkDir
    $env:PATH = "$sdkDir;$env:PATH"
    $env:DOTNET_CLI_TELEMETRY_OPTOUT = '1'
    & (Join-Path $PSScriptRoot 'Compilar-Instalar.ps1') -RevitVersion 2026 -RevitPath $revitPath -Framework $framework
    Write-Host 'Instalacao concluida. Abra o Revit 2026 e procure TOPOBIM.' -ForegroundColor Green
} catch {
    Write-Host $_.Exception.Message -ForegroundColor Red
    exit 1
}
