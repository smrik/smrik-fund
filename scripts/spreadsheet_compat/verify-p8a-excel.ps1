param(
    [Parameter(Mandatory = $true)][string]$WorkbookPath,
    [Parameter(Mandatory = $true)][string]$ResultsPath
)

$ErrorActionPreference = 'Stop'
$tolerance = 1e-8
$fullWorkbook = [System.IO.Path]::GetFullPath($WorkbookPath)
$fullResults = [System.IO.Path]::GetFullPath($ResultsPath)
$proofPath = Join-Path ([System.IO.Path]::GetDirectoryName($fullWorkbook)) 'tax-verification.json'
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

$extension = [System.IO.Path]::GetExtension($fullWorkbook)
if ($extension -ne '.xlsx') { throw "P8A native proof requires an .xlsx workbook: $fullWorkbook" }
New-Item -ItemType Directory -Force -Path $privateDirectory | Out-Null
[System.IO.File]::Copy($fullWorkbook, $working, $true)
if (-not (Test-Path -LiteralPath $working -PathType Leaf)) { throw "P8A private workbook copy was not created: $working" }
$publishedBefore = Sha256 $fullWorkbook
if ($publishedBefore -ne $proof.publishedSha256) { throw 'Mog verification does not match this workbook fingerprint' }
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
    $excel.Calculation = -4105 # xlCalculationAutomatic; set after opening
    $excel.Iteration = $false
    $excel.CalculateBeforeSave = $true
    $book.ForceFullCalculation = $true
    $excel.CalculateFullRebuild()
    $inputs = $book.Worksheets.Item('Inputs')
    $taxes = $book.Worksheets.Item('Taxes')
    $income = $book.Worksheets.Item('Income')
    $cash = $book.Worksheets.Item('CashFlow')
    $bs = $book.Worksheets.Item('BalanceSheet')
    $dcf = $book.Worksheets.Item('DCF')
    $checks = $book.Worksheets.Item('Checks')
    $review = $book.Worksheets.Item('Review')
    $sensitivity = $book.Worksheets.Item('Sensitivity')

    foreach ($column in @('B','C','D','E','F','G','H','I','J','K','L')) {
        if ((Value $checks "${column}20") -ne 'PASS') { throw "Excel check failed at ${column}20" }
        if ((Value $taxes "${column}30") -ne 'PASS') { throw "Excel tax check failed at ${column}30" }
    }
    if ((Value $inputs 'B114') -ne 'PASS') { throw 'Excel P8A gate failed' }
    Assert-Close (Value $bs 'B28') 0 'Excel balance difference'
    Assert-Close (Value $taxes 'B11') $proof.snapshot.tax.bookTaxExpense[0] 'Excel/Mog book tax'
    Assert-Close (Value $taxes 'B17') $proof.snapshot.tax.currentTaxPayment[0] 'Excel/Mog current tax payment'
    Assert-Close (Value $taxes 'B22') $proof.snapshot.tax.deferredTaxLiabilityClosing[0] 'Excel/Mog DTL'
    Assert-Close (Value $taxes 'B29') $proof.snapshot.tax.operatingTaxExpense[0] 'Excel/Mog operating tax'
    Assert-Close (Value $cash 'B12') $proof.snapshot.stub.cfo 'Excel/Mog CFO'
    Assert-Close (Value $cash 'B18') $proof.snapshot.stub.closingCash 'Excel/Mog closing cash'
    Assert-Close (Value $dcf 'B7') $proof.snapshot.stub.economicUfcf 'Excel/Mog economic UFCF'
    Assert-Close (Value $dcf 'B18') $proof.snapshot.enterpriseValue 'Excel/Mog enterprise value'
    Assert-Close (Value $sensitivity 'C5') (Value $dcf 'B18') 'Excel sensitivity center'
    $formulas = [ordered]@{
        tax = Assert-Formula $taxes 'B11' 'Taxes!B11'
        currentPayableClosing = Assert-Formula $taxes 'B16' 'Taxes!B16'
        currentPayment = Assert-Formula $taxes 'B17' 'Taxes!B17'
        deferredLiability = Assert-Formula $taxes 'B22' 'Taxes!B22'
        operatingTax = Assert-Formula $taxes 'B29' 'Taxes!B29'
        incomePretax = Assert-Formula $income 'B13' 'Income!B13'
        cash = Assert-Formula $cash 'B18' 'CashFlow!B18'
    }

    $baseBook = [double](Value $inputs 'B106')
    $baseOperating = [double](Value $inputs 'B107')
    $baseBookTax = [double](Value $taxes 'B11')
    $baseOperatingTax = [double](Value $taxes 'B29')
    $baseNetIncome = [double](Value $income 'B15')
    $baseCurrentCashTax = [double](Value $taxes 'B17')
    $baseCurrentClosing = [double](Value $taxes 'B16')
    $basePayableDays = [double](Value $inputs 'B117')
    $baseDtl = [double](Value $taxes 'B22')
    $baseCfo = [double](Value $cash 'B12')
    $baseClosingCash = [double](Value $cash 'B18')
    $baseUfcf = [double](Value $dcf 'B7')
    $baseDeferredShares = @{}
    foreach ($column in @('B','C','D','E','F','G','H','I','J','K','L')) { $baseDeferredShares[$column] = [double](Value $inputs "${column}108") }
    $inputs.Range('B106').Value2 = $baseBook * 0.8
    $excel.CalculateFullRebuild()
    $bookRateEdit = [ordered]@{ bookTax = Value $taxes 'B11'; operatingTax = Value $taxes 'B29' }
    if ([math]::Abs(([double]$bookRateEdit.bookTax) - $baseBookTax) -le $tolerance) { throw 'Excel book-rate edit did not change book tax' }
    Assert-Close $bookRateEdit.operatingTax $baseOperatingTax 'Excel operating tax independent of book rate'
    $inputs.Range('B106').Value2 = $baseBook
    $inputs.Range('B107').Value2 = $baseOperating * 0.8
    $excel.CalculateFullRebuild()
    $operatingRateEdit = [ordered]@{ bookTax = Value $taxes 'B11'; operatingTax = Value $taxes 'B29'; ufcf = Value $dcf 'B7' }
    Assert-Close $operatingRateEdit.bookTax $baseBookTax 'Excel book tax independent of operating rate'
    if ([math]::Abs(([double]$operatingRateEdit.operatingTax) - $baseOperatingTax) -le $tolerance -or [math]::Abs(([double]$operatingRateEdit.ufcf) - [double]$proof.snapshot.stub.economicUfcf) -le $tolerance) { throw 'Excel operating-rate edit did not propagate to operating tax/UFCF' }
    $inputs.Range('B107').Value2 = $baseOperating

    $baseDeferredShare = [double](Value $inputs 'B108')
    $baseDtl = [double](Value $taxes 'B22')
    $inputs.Range('B108').Value2 = 0.2
    $excel.CalculateFullRebuild()
    if ([math]::Abs(([double](Value $taxes 'B13'))) -le $tolerance -or [double](Value $taxes 'B22') -le $baseDtl) { throw 'Excel deferred-share edit did not change deferred tax/DTL' }
    foreach ($column in @('B','C','D','E','F','G','H','I','J','K','L')) { $inputs.Range("${column}108").Value2 = $baseDeferredShares[$column] }
    $baseCurrentPayment = [double](Value $taxes 'B17')
    $inputs.Range('B117').Value2 = $basePayableDays + 1
    $excel.CalculateFullRebuild()
    if ([math]::Abs(([double](Value $taxes 'B17')) - $baseCurrentPayment) -le $tolerance) { throw 'Excel current-payable timing edit did not change cash payment' }
    $inputs.Range('B117').Value2 = $basePayableDays
    $inputs.Range('B108').Value2 = 0
    $excel.CalculateFullRebuild()
    if ((Value $inputs 'B114') -ne 'PASS') { throw 'Excel explicit numeric zero rejected' }
    foreach ($column in @('B','C','D','E','F','G','H','I','J','K','L')) { $inputs.Range("${column}108").Value2 = $baseDeferredShares[$column] }

    # A supported first-stub deferred benefit reverses the existing DTL. All
    # values below are read after Excel recalculation; no expected closing
    # balance is injected into a formula-owned output.
    $inputs.Range('B108').Value2 = -0.1
    foreach ($column in @('C','D','E','F','G','H','I','J','K','L')) { $inputs.Range("${column}108").Value2 = 0 }
    $excel.CalculateFullRebuild()
    if ((Value $inputs 'B114') -ne 'PASS' -or (Value $dcf 'B24') -eq 'BLOCKED') { throw 'Excel supported deferred reversal was blocked' }
    foreach ($column in @('B','C','D','E','F','G','H','I','J','K','L')) {
        if ((Value $taxes "${column}30") -ne 'PASS' -or (Value $checks "${column}20") -ne 'PASS') { throw "Excel reversal check failed at ${column}" }
    }
    Assert-Close (Value $taxes 'B11') $baseBookTax 'Excel reversal book tax'
    Assert-Close (Value $income 'B15') $baseNetIncome 'Excel reversal net income'
    Assert-Close (Value $taxes 'B13') (-0.1 * $baseBookTax) 'Excel reversal deferred benefit'
    Assert-Close (Value $taxes 'B22') ($baseDtl - 0.1 * $baseBookTax) 'Excel reversal closing DTL'
    if ([double](Value $taxes 'B22') -le 0) { throw 'Excel reversal DTL became nonpositive' }
    $expectedCurrentCashTaxDelta = if ((Value $inputs 'B116') -eq 'source_anchored_payable_days') { 0.1 * ($baseBookTax - $baseCurrentClosing) } else { 0.1 * $baseBookTax }
    Assert-Close ((Value $taxes 'B17') - $baseCurrentCashTax) $expectedCurrentCashTaxDelta 'Excel reversal current cash-tax effect'
    Assert-Close ((Value $cash 'B12') - $baseCfo) (-$expectedCurrentCashTaxDelta) 'Excel reversal CFO effect'
    Assert-Close ((Value $cash 'B18') - $baseClosingCash) (-$expectedCurrentCashTaxDelta) 'Excel reversal closing-cash effect'
    Assert-Close (Value $taxes 'B29') $baseOperatingTax 'Excel reversal operating tax independence'
    Assert-Close (Value $dcf 'B7') $baseUfcf 'Excel reversal UFCF independence'
    foreach ($column in @('B','C','D','E','F','G','H','I','J','K','L')) { $inputs.Range("${column}108").Value2 = $baseDeferredShares[$column] }
    $excel.CalculateFullRebuild()

    # Final-period edits must be caught by the linked closing rows and the
    # combined gate, rather than only by the next period's opening balance.
    $baseSettlement = [double](Value $inputs 'L110')
    $openingLongTerm = [double](Value $inputs 'B112')
    $inputs.Range('L110').Value2 = $openingLongTerm + 1
    $excel.CalculateFullRebuild()
    if ((Value $taxes 'L30') -ne 'FAIL' -or (Value $inputs 'B114') -ne 'FAIL' -or (Value $dcf 'B24') -ne 'BLOCKED') { throw 'Excel final-period over-settlement was not blocked' }
    $inputs.Range('L110').Value2 = $baseSettlement
    $excel.CalculateFullRebuild()

    $inputs.Range('B117').Value2 = 365
    $excel.CalculateFullRebuild()
    if ((Value $taxes 'B30') -ne 'FAIL' -or (Value $inputs 'B114') -ne 'FAIL' -or (Value $dcf 'B24') -ne 'BLOCKED') { throw 'Excel negative current cash payment was not blocked' }
    $inputs.Range('B117').Value2 = $basePayableDays
    $excel.CalculateFullRebuild()

    $inputs.Range('B108').Value2 = -1
    $excel.CalculateFullRebuild()
    if ((Value $taxes 'B30') -ne 'FAIL' -or (Value $inputs 'B114') -ne 'FAIL' -or (Value $dcf 'B24') -ne 'BLOCKED') { throw 'Excel cross-period DTL underflow was not blocked' }
    foreach ($column in @('B','C','D','E','F','G','H','I','J','K','L')) { $inputs.Range("${column}108").Value2 = $baseDeferredShares[$column] }
    $excel.CalculateFullRebuild()
    if ((Value $inputs 'B114') -ne 'PASS' -or (Value $dcf 'B24') -eq 'BLOCKED') { throw 'Excel did not recover after P8A adverse edits' }
    $inputs.Range('B117').ClearContents()
    $excel.CalculateFullRebuild()
    if ((Value $inputs 'B114') -ne 'FAIL' -or (Value $dcf 'B18') -ne 'BLOCKED') { throw 'Excel missing payable-days input was not blocked' }
    $inputs.Range('B117').Value2 = $basePayableDays
    $excel.CalculateFullRebuild()
    Assert-Close (Value $bs 'B28') 0 'Excel recovery balance difference'
    if ((Value $review 'B3') -eq 'BLOCKED') { throw 'Excel recovery did not restore review status' }
    $book.Close($false)
    $book = $null
    $excel.Quit()
    $excel = $null
    $result = [ordered]@{
        status = 'PASS'
        mode = 'native invisible Excel P8A recalculation plus rate/timing/reversal/adverse edits'
        publishedSha256Before = $publishedBefore
        publishedSha256After = Sha256 $fullWorkbook
        workbookPath = $fullWorkbook
        formulas = $formulas
        edits = [ordered]@{ bookRate = $bookRateEdit; operatingRate = $operatingRateEdit; deferredShare = 'DTL changed; source gate PASS'; supportedReversal = 'first-stub -0.1; book/NI unchanged; DTL positive; timing-aware CFO/cash effect; operating tax/UFCF unchanged'; currentPayable = 'payable-days edit changed payment; missing days FAIL/BLOCKED'; finalSettlement = 'closing LT liability FAIL/BLOCKED'; negativeCashPayment = 'FAIL/BLOCKED'; dtlUnderflow = 'FAIL/BLOCKED'; numericZero = 'PASS' }
        checks = @('Mog fingerprint and values match', 'Taxes B30:L30 all PASS', 'Checks B20:L20 all PASS', 'book/operating rate independence', 'deferred share and DTL roll', 'supported deferred reversal', 'current payable timing', 'final settlement/negative cash/DTL adverse edits', 'missing versus numeric zero', 'Excel recovery and published bytes preserved')
    }
    $result | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $fullResults -Encoding utf8
    Write-Output ($result | ConvertTo-Json -Depth 8)
} finally {
    if ($book -ne $null) { $book.Close($false) }
    if ($excel -ne $null) { $excel.Quit() }
    Remove-Item -LiteralPath $working -Force -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath $privateDirectory -Recurse -Force -ErrorAction SilentlyContinue
}
