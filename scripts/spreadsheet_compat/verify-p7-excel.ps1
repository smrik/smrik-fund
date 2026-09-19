param(
  [Parameter(Mandatory = $true)][string]$WorkbookPath,
  [string]$OutputPath = ""
)

$ErrorActionPreference = "Stop"
$resolvedWorkbook = (Resolve-Path -LiteralPath $WorkbookPath).Path
if ([string]::IsNullOrWhiteSpace($OutputPath)) {
  $OutputPath = Join-Path (Split-Path -Parent $resolvedWorkbook) "p7-excel-verification.json"
}
$beforeHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $resolvedWorkbook).Hash
$scratch = Join-Path ([System.IO.Path]::GetTempPath()) ("p7-excel-" + [guid]::NewGuid().ToString("N") + ".xlsx")
Copy-Item -LiteralPath $resolvedWorkbook -Destination $scratch
$excel = $null
$book = $null
try {
  $excel = New-Object -ComObject Excel.Application
  $excel.Visible = $false
  $excel.DisplayAlerts = $false
  $book = $excel.Workbooks.Open($scratch, $null, $false)
  $excel.Calculation = -4105 # xlCalculationAutomatic
  $book.ForceFullCalculation = $true
  $excel.CalculateFullRebuild()
  $inputs = $book.Worksheets.Item("Inputs")
  $wc = $book.Worksheets.Item("WorkingCapital")
  $cash = $book.Worksheets.Item("CashFlow")
  $dcf = $book.Worksheets.Item("DCF")
  $sourceValues = @{
    accountsReceivable = [double]$inputs.Range("B8").Value2
    inventory = [double]$inputs.Range("B9").Value2
    contractCurrent = [double]$inputs.Range("B93").Value2
    otherOclResidual = [double]$inputs.Range("B91").Value2
  }
  if ([math]::Abs($sourceValues.otherOclResidual - 8194) -gt 1e-8) { throw "P7 unclassified OCL residual is not 8,194" }
  if (-not ([string]$wc.Range("B10").Formula).StartsWith("=")) { throw "WorkingCapital B10 is not a formula" }
  if (-not ([string]$wc.Range("B33").Formula).StartsWith("=")) { throw "WorkingCapital B33 is not a formula" }
  if (-not ([string]$wc.Range("B42").Formula).StartsWith("=")) { throw "WorkingCapital B42 is not a formula" }
  $baseAr = [double]$wc.Range("B10").Value2
  $baseCash = [double]$cash.Range("B15").Value2
  $dso = [double]$inputs.Range("B82").Value2
  $inputs.Range("B82").Value2 = $dso + 10
  $excel.CalculateFullRebuild()
  $dsoAr = [double]$wc.Range("B10").Value2
  $dsoCash = [double]$cash.Range("B15").Value2
  if ([math]::Abs($dsoAr - $baseAr) -le 1e-8 -or [math]::Abs($dsoCash - $baseCash) -le 1e-8) { throw "DSO edit did not change AR and cash" }
  $inputs.Range("B82").ClearContents()
  $excel.CalculateFullRebuild()
  if ([string]$inputs.Range("B100").Value2 -ne "FAIL" -or [string]$dcf.Range("B18").Value2 -ne "BLOCKED") { throw "missing DSO did not fail and block" }
  $inputs.Range("B82").Value2 = 0
  $excel.CalculateFullRebuild()
  if ([string]$inputs.Range("B100").Value2 -ne "PASS") { throw "supported zero DSO did not recover gate" }
  $result = [ordered]@{
    status = "PASS"
    mode = "private invisible native Excel recalculation/edit proof"
    workbook = $resolvedWorkbook
    sourceValues = $sourceValues
    formulas = @{ currentAr = $wc.Range("B10").Formula; contract = $wc.Range("B33").Formula; nwc = $wc.Range("B42").Formula }
    dsoEdit = @{ baseAr = $baseAr; changedAr = $dsoAr; baseCash = $baseCash; changedCash = $dsoCash }
    missingAndZero = "missing DSO FAIL/BLOCKED; zero DSO PASS"
  }
  $book.Close($false)
  $book = $null
  $excel.Quit()
  $excel = $null
  $afterHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $resolvedWorkbook).Hash
  if ($beforeHash -ne $afterHash) { throw "published workbook bytes changed" }
  $result["publishedSha256"] = $afterHash
  $json = $result | ConvertTo-Json -Depth 10
  New-Item -ItemType Directory -Force -Path (Split-Path -Parent $OutputPath) | Out-Null
  Set-Content -LiteralPath $OutputPath -Value $json -Encoding UTF8
  Write-Output $json
}
finally {
  if ($book -ne $null) { $book.Close($false) }
  if ($excel -ne $null) { $excel.Quit() }
  if ($book -ne $null) { [void][System.Runtime.InteropServices.Marshal]::ReleaseComObject($book) }
  if ($excel -ne $null) { [void][System.Runtime.InteropServices.Marshal]::ReleaseComObject($excel) }
  if (Test-Path -LiteralPath $scratch) { Remove-Item -LiteralPath $scratch -Force }
}
