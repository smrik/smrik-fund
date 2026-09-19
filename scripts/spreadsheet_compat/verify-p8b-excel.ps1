param(
    [Parameter(Mandatory = $true)][string]$WorkbookPath,
    [Parameter(Mandatory = $true)][string]$ResultsPath
)

$ErrorActionPreference = 'Stop'
$tolerance = 1e-8
$fullWorkbook = [System.IO.Path]::GetFullPath($WorkbookPath)
$fullResults = [System.IO.Path]::GetFullPath($ResultsPath)
$proofPath = Join-Path ([System.IO.Path]::GetDirectoryName($fullWorkbook)) 'financing-verification.json'
$proof = Get-Content -LiteralPath $proofPath -Raw | ConvertFrom-Json
$privateDirectory = Join-Path ([System.IO.Path]::GetDirectoryName($fullWorkbook)) ('.native-excel-' + [guid]::NewGuid().ToString('N'))
$working = Join-Path $privateDirectory ([System.IO.Path]::GetFileName($fullWorkbook))

function Sha256([string]$path) {
    $sha = [System.Security.Cryptography.SHA256]::Create()
    try { return ([System.BitConverter]::ToString($sha.ComputeHash([System.IO.File]::ReadAllBytes($path)))).Replace('-', '').ToLowerInvariant() }
    finally { $sha.Dispose() }
}
function Value($sheet, [string]$address) {
    $value = $sheet.Range($address).Value2
    if ($null -eq $value) { return $null }
    if ($value -is [double] -or $value -is [decimal] -or $value -is [int] -or $value -is [long]) { return [double]$value }
    return [string]$value
}
function Assert-Close($actual, $expected, [string]$label) {
    if ($null -eq $actual -or $actual -is [string] -or $null -eq $expected) { throw "$label is missing or nonnumeric" }
    if ([math]::Abs(([double]$actual) - ([double]$expected)) -gt $tolerance) { throw "$label expected $expected, got $actual" }
}
function Assert-Formula($sheet, [string]$address, [string]$label) {
    $formula = [string]$sheet.Range($address).Formula
    if (-not $formula.StartsWith('=')) { throw "$label lost formula: $formula" }
    return $formula
}

if ([System.IO.Path]::GetExtension($fullWorkbook) -ne '.xlsx') { throw "P8B native proof requires an .xlsx workbook: $fullWorkbook" }
New-Item -ItemType Directory -Force -Path $privateDirectory | Out-Null
[System.IO.File]::Copy($fullWorkbook, $working, $true)
$publishedBefore = Sha256 $fullWorkbook
if ($publishedBefore -ne [string]$proof.publishedSha256) { throw 'Mog verification does not match this workbook fingerprint' }
$excel = $null
$book = $null
try {
    $excel = New-Object -ComObject Excel.Application
    $excel.Visible = $false
    $excel.DisplayAlerts = $false
    $excel.ScreenUpdating = $false
    $excel.EnableEvents = $false
    $excel.AutomationSecurity = 3
    $book = $excel.Workbooks.Open($working, 0, $false)
    $excel.Calculation = -4105
    $excel.Iteration = $false
    $excel.CalculateBeforeSave = $true
    $book.ForceFullCalculation = $true
    $excel.CalculateFullRebuild()

    $inputs = $book.Worksheets.Item('Inputs')
    $financing = $book.Worksheets.Item('Financing')
    $runoff = $book.Worksheets.Item('FinancingRunoff')
    $income = $book.Worksheets.Item('Income')
    $cash = $book.Worksheets.Item('CashFlow')
    $bs = $book.Worksheets.Item('BalanceSheet')
    $dcf = $book.Worksheets.Item('DCF')
    $checks = $book.Worksheets.Item('Checks')
    $review = $book.Worksheets.Item('Review')
    $sensitivity = $book.Worksheets.Item('Sensitivity')

    foreach ($column in @('B','C','D','E','F','G','H','I','J','K','L')) {
        if ((Value $checks "${column}20") -ne 'PASS') { throw "Excel mechanical check failed at ${column}20" }
        if ((Value $financing "${column}27") -ne 'PASS') { throw "Excel debt check failed at ${column}27" }
        if ((Value $financing "${column}74") -ne 'PASS') { throw "Excel lease calibration check failed at ${column}74" }
    }
    if ((Value $inputs 'B146') -ne 'PASS') { throw 'Excel P8B input gate failed' }
    Assert-Close (Value $inputs 'B169') 13 'Excel selected opening finance service life'
    if ((Value $checks 'B22') -ne 'PASS') { throw 'Excel all-period gate failed' }
    Assert-Close (Value $bs 'B32') 0 'Excel balance difference'
    Assert-Close (Value $financing 'B13') $proof.snapshot.financing.debtClosingFace[0] 'Excel/Mog debt face'
    Assert-Close (Value $financing 'B17') $proof.snapshot.financing.debtClosingContra[0] 'Excel/Mog debt contra'
    Assert-Close (Value $financing 'B52') $proof.snapshot.financing.operatingLiabilityClosing[0] 'Excel/Mog operating liability'
    Assert-Close (Value $financing 'B55') $proof.snapshot.financing.financePpeClosing[0] 'Excel/Mog finance PP&E'
    Assert-Close (Value $financing 'B56') $proof.snapshot.financing.operatingPayment[0] 'Excel/Mog operating lease cash'
    Assert-Close (Value $financing 'B57') $proof.snapshot.financing.financePayment[0] 'Excel/Mog finance lease cash'
    Assert-Close (Value $cash 'B12') $proof.snapshot.stub.cfo 'Excel/Mog CFO'
    Assert-Close (Value $cash 'B18') $proof.snapshot.stub.closingCash 'Excel/Mog closing cash'
    Assert-Close (Value $dcf 'B7') $proof.snapshot.stub.economicUfcf 'Excel/Mog economic UFCF'
    Assert-Close (Value $dcf 'B18') $proof.snapshot.enterpriseValue 'Excel/Mog enterprise value'
    Assert-Close (Value $sensitivity 'C5') (Value $dcf 'B18') 'Excel sensitivity center'
    $formulas = [ordered]@{
        debtFace = Assert-Formula $financing 'B13' 'Financing!B13'
        debtInterest = Assert-Formula $financing 'B14' 'Financing!B14'
        operatingLiability = Assert-Formula $financing 'B52' 'Financing!B52'
        financePpe = Assert-Formula $financing 'B55' 'Financing!B55'
        cash = Assert-Formula $cash 'B18' 'CashFlow!B18'
        balance = Assert-Formula $bs 'B32' 'BalanceSheet!B32'
        ufcf = Assert-Formula $dcf 'B7' 'DCF!B7'
    }

    $baseCoupon = [double](Value $inputs 'B125')
    $baseInterest = [double](Value $financing 'B14')
    $inputs.Range('B125').Value2 = $baseCoupon * 0.8
    $excel.CalculateFullRebuild()
    if ([math]::Abs(([double](Value $financing 'B14')) - $baseInterest) -le $tolerance) { throw 'Excel bounded debt-rate edit did not propagate' }
    if ((Value $review 'B3') -ne 'EDITED_UNREVIEWED') { throw 'Excel debt-rate edit did not invalidate review binding' }
    $inputs.Range('B125').Value2 = $baseCoupon
    $excel.CalculateFullRebuild()
    if ((Value $inputs 'B146') -ne 'PASS' -or (Value $review 'B3') -eq 'BLOCKED') { throw 'Excel did not recover after debt-rate edit' }

    $baseOperatingPayment = [double](Value $inputs 'B150')
    $inputs.Range('B150').ClearContents()
    $excel.CalculateFullRebuild()
    if ((Value $inputs 'B146') -ne 'FAIL' -or (Value $dcf 'B18') -ne 'BLOCKED') { throw 'Excel missing opening payment was not blocked' }
    $inputs.Range('B150').Value2 = $baseOperatingPayment
    $excel.CalculateFullRebuild()
    if ((Value $inputs 'B146') -ne 'PASS' -or (Value $checks 'B22') -ne 'PASS') { throw 'Excel did not recover after missing payment' }

    $inputs.Range('B163').Value2 = 0
    $excel.CalculateFullRebuild()
    if ((Value $inputs 'B146') -ne 'PASS') { throw 'Excel numeric zero pipeline interest was rejected' }

    $book.Close($false)
    $book = $null
    $excel.Quit()
    $excel = $null
    $publishedAfter = Sha256 $fullWorkbook
    if ($publishedBefore -ne $publishedAfter) { throw 'Published workbook bytes changed during private Excel proof' }
    $result = [ordered]@{
        status = 'PASS'
        mode = 'native invisible Excel P8B recalculation plus debt-rate and missing-input guards'
        publishedSha256Before = $publishedBefore
        publishedSha256After = $publishedAfter
        workbookPath = $fullWorkbook
        formulas = $formulas
        checks = @('Mog fingerprint and values match', 'Checks B20:L20 all PASS', 'Financing debt/calibration checks all PASS', 'P8B gate PASS', 'review binding invalidates on debt-rate edit', 'missing opening payment FAIL/BLOCKED and recovery', 'numeric zero accepted', 'published bytes preserved')
    }
    $result | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $fullResults -Encoding utf8
    Write-Output ($result | ConvertTo-Json -Depth 8)
} finally {
    if ($book -ne $null) { $book.Close($false) }
    if ($excel -ne $null) { $excel.Quit() }
    Remove-Item -LiteralPath $working -Force -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath $privateDirectory -Recurse -Force -ErrorAction SilentlyContinue
}
