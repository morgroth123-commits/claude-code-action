$ErrorActionPreference = "Stop"

$repository = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..")).Path
$venvPython = Join-Path $repository ".venv\Scripts\python.exe"
$python = if (Test-Path -LiteralPath $venvPython) { $venvPython } else { "python" }

Push-Location $repository
try {
    & $python -m PyInstaller --noconfirm --clean ChatMPD.spec
    if ($LASTEXITCODE -ne 0) {
        throw "PyInstaller failed with exit code $LASTEXITCODE"
    }
    $executable = Join-Path $repository "dist\ChatMPD.exe"
    if (-not (Test-Path -LiteralPath $executable -PathType Leaf)) {
        throw "The build completed without creating dist\ChatMPD.exe"
    }
    $sourceGuide = Join-Path $repository "docs\most-effective-usage.md"
    $distGuide = Join-Path $repository "dist\Most Effective Usage.md"
    Copy-Item -LiteralPath $sourceGuide -Destination $distGuide -Force
    Get-Item -LiteralPath $executable, $distGuide | Select-Object FullName, Length, LastWriteTime
    Get-FileHash -LiteralPath $executable -Algorithm SHA256
}
finally {
    Pop-Location
}
