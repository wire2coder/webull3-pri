$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$Src = Join-Path $Root "tradeconfirmation"
$Dest = Join-Path $Root "done1"

New-Item -ItemType Directory -Force -Path $Src, $Dest | Out-Null

$Files = Get-ChildItem -Path $Src -File
$Count = $Files.Count
Write-Host "Files in tradeconfirmation: $Count"

if ($Count -eq 0) {
    Write-Host "Nothing to move."
    exit 0
}

$Files | Move-Item -Destination $Dest
Write-Host "Moved $Count file(s) to done1."
