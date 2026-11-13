param(
    [string]$PyRevitRoot = "$env:APPDATA/pyRevit-Master",
    [Parameter(Mandatory = $true)][string]$StandardLibrary,
    [string]$RenderDirectory = ''
)
$ErrorActionPreference = 'Stop'
# Windows PowerShell tests netfx; PowerShell 7 tests netcore (as in Revit 2026).
# Both use a simulated host; no Revit model is opened.
$runtimeFolder = if ($PSVersionTable.PSEdition -eq 'Core') { 'netcore' } else { 'netfx' }
$engineDirectory = Join-Path $PyRevitRoot "bin/$runtimeFolder/engines/IPY2712PR"
foreach ($assemblyName in @('pyRevitLabs.Microsoft.Scripting.dll', 'pyRevitLabs.Microsoft.Dynamic.dll',
                            'pyRevitLabs.IronPython.dll', 'pyRevitLabs.IronPython.Modules.dll',
                            'pyRevitLabs.IronPython.Wpf.dll')) {
    [void][Reflection.Assembly]::LoadFrom((Join-Path $engineDirectory $assemblyName))
}
$engineOptions = New-Object 'System.Collections.Generic.Dictionary[string,object]'
$engineOptions.Add('LightweightScopes', $true)
$engineOptions.Add('RecursionLimit', 1000)
$engine = [IronPython.Hosting.Python]::CreateEngine($engineOptions)
$paths = $engine.GetSearchPaths()
$paths.Add((Resolve-Path -LiteralPath $StandardLibrary).Path)
$paths.Add($PSScriptRoot)
$paths.Add($engineDirectory)
$engine.SetSearchPaths($paths)
$scope = $engine.CreateScope()
if ($RenderDirectory) {
    [void](New-Item -ItemType Directory -Path $RenderDirectory -Force)
    $scope.SetVariable('QA_OUTPUT', (Resolve-Path -LiteralPath $RenderDirectory).Path)
}
$scope.SetVariable('TEST_DIRECTORY', $PSScriptRoot)
# Run first, before the ordinary suite warms/JIT-compiles the parsing functions.
$scope.SetVariable('STACK_TEST_FILE', (Join-Path $PSScriptRoot 'verify_floor_csv_stack.py'))
$engine.Execute('execfile(STACK_TEST_FILE, dict(globals(), __file__=STACK_TEST_FILE))', $scope)
$engine.Execute('import unittest; result = unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.discover(TEST_DIRECTORY)); assert result.wasSuccessful()', $scope)
$scope.SetVariable('WPF_TEST_FILE', (Join-Path $PSScriptRoot 'verify_wpf.py'))
$engine.Execute(@'
import traceback
try:
    execfile(WPF_TEST_FILE, dict(globals(), __file__=WPF_TEST_FILE))
except Exception:
    print(traceback.format_exc())
    raise
'@, $scope)
