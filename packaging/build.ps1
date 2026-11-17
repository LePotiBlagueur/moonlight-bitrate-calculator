<#
    Construit les exécutables Windows.
    À lancer depuis la racine du dépôt, sous Windows, avec Python 3.11+ :

        powershell -ExecutionPolicy Bypass -File packaging\build.ps1
#>
$ErrorActionPreference = "Stop"

if (-not (Test-Path "packaging\moonlight.spec")) {
    throw "Lancez ce script depuis la racine du depot."
}

Write-Host "== Environnement virtuel de build ==" -ForegroundColor Cyan
if (-not (Test-Path ".venv-build")) { python -m venv .venv-build }
$py = ".venv-build\Scripts\python.exe"

& $py -m pip install --upgrade pip wheel | Out-Null
& $py -m pip install -e . pyinstaller

Write-Host "== Tests ==" -ForegroundColor Cyan
& $py -m unittest discover -s . -p "test_*.py" -q
if ($LASTEXITCODE -ne 0) { throw "Les tests echouent : build annule." }

Write-Host "== PyInstaller ==" -ForegroundColor Cyan
& $py -m PyInstaller --clean --noconfirm packaging\moonlight.spec

Copy-Item config.example.toml dist\ -Force
Copy-Item README.md dist\ -Force

Write-Host "`n== Verification ==" -ForegroundColor Cyan
& dist\moonlight-recap.exe --version
& dist\moonlight-recap.exe -b 450 --sections best --no-color

Write-Host "`nExecutables prets dans dist\ :" -ForegroundColor Green
Get-ChildItem dist\*.exe | ForEach-Object {
    "{0,-26} {1,8:N1} Mo" -f $_.Name, ($_.Length / 1MB)
}
