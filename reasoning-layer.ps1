param([Parameter(ValueFromRemainingArguments=$true)][string[]]$LayerArguments)
$layerRoot = $PSScriptRoot
$layerPython = Join-Path $env:USERPROFILE 'fleet\venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $layerPython)) { $layerPython = (Get-Command python -ErrorAction Stop).Source }
$previousPythonPath = $env:PYTHONPATH
try {
    $env:PYTHONPATH = $layerRoot + [IO.Path]::PathSeparator + $previousPythonPath
    & $layerPython -X utf8 -m reasoning_layer @LayerArguments
    $layerExit = $LASTEXITCODE
} finally {
    $env:PYTHONPATH = $previousPythonPath
}
exit $layerExit
