param(
    [Parameter(Mandatory = $true)][string]$WorkbookPath,
    [Parameter(Mandatory = $true)][string]$ResultsPath
)

$ErrorActionPreference = 'Stop'
$tolerance = 1e-8
$fullWorkbook = [System.IO.Path]::GetFullPath($WorkbookPath)
$fullResults = [System.IO.Path]::GetFullPath($ResultsPath)
$proofPath = Join-Path ([System.IO.Path]::GetDirectoryName($fullWorkbook)) 'p8d-verification.json'
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
function Assert-Changed($actual, $baseline, [string]$label) {
    if ($null -eq $actual -or $actual -is [string] -or $null -eq $baseline -or $baseline -is [string]) { throw "$label is missing or nonnumeric" }
    if ([math]::Abs(([double]$actual) - ([double]$baseline)) -le $tolerance) { throw "$label did not change" }
}
function Assert-Formula($sheet, [string]$address, [string]$label) {
    $formula = [string]$sheet.Range($address).Formula
    if (-not $formula.StartsWith('=')) { throw "$label lost formula: $formula" }
    return $formula
}
function Recalculate($excel) {
    $excel.CalculateFullRebuild()
    Start-Sleep -Milliseconds 250
}

if ([System.IO.Path]::GetExtension($fullWorkbook) -ne '.xlsx') { throw "P8D native proof requires an .xlsx workbook: $fullWorkbook" }
New-Item -ItemType Directory -Force -Path $privateDirectory | Out-Null
New-Item -ItemType Directory -Force -Path ([System.IO.Path]::GetDirectoryName($fullResults)) | Out-Null
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
    Recalculate $excel

    $inputs = $book.Worksheets.Item('Inputs')
    $income = $book.Worksheets.Item('Income')
    $cash = $book.Worksheets.Item('CashFlow')
    $bs = $book.Worksheets.Item('BalanceSheet')
    $other = $book.Worksheets.Item('OtherBalances')
    $financing = $book.Worksheets.Item('Financing')
    $workingCapital = $book.Worksheets.Item('WorkingCapital')
    $taxes = $book.Worksheets.Item('Taxes')
    $dcf = $book.Worksheets.Item('DCF')
    $checks = $book.Worksheets.Item('Checks')
    $review = $book.Worksheets.Item('Review')

    foreach ($column in @('B','C','D','E','F','G','H','I','J','K','L')) {
        if ((Value $checks "${column}20") -ne 'PASS') { throw "Excel mechanical check failed at ${column}20" }
        if ((Value $other "${column}22") -ne 'PASS') { throw "Excel P8D coverage failed at ${column}22" }
    }
    if ((Value $inputs 'B253') -ne 'PASS') { throw 'Excel P8D input gate failed' }
    if ((Value $checks 'B22') -ne 'PASS') { throw 'Excel all-period gate failed' }
    $sourceEquityOther = [double](Value $inputs 'B244')
    $sourceKnownInvestment = [double](Value $inputs 'B269')
    $sourceOtherInvestmentPool = [double](Value $inputs 'B268')
    $sourceFinancingReceivables = [double](Value $inputs 'B245')
    $sourceUnfundedCommitment = [double](Value $inputs 'B270')
    $selectedFraction = [double](Value $inputs 'B238')
    $selectedGain = [double](Value $inputs 'B241')
    $expectedCommitmentAdjustment = $sourceUnfundedCommitment * ($selectedFraction - 1) / [math]::Pow(1.043, 91.0 / 365.0)
    $expectedInvestmentCarrying = $sourceEquityOther + $sourceUnfundedCommitment + $selectedGain
    $expectedInvestmentValue = $sourceKnownInvestment + $sourceOtherInvestmentPool * [double](Value $inputs 'B234') + $sourceFinancingReceivables + $expectedCommitmentAdjustment
    Assert-Close (Value $other 'B10') $expectedInvestmentCarrying 'Excel/Mog selected investment carrying'
    Assert-Close (Value $other 'B11') $expectedInvestmentValue 'Excel/Mog selected investment value'
    Assert-Close (Value $other 'B24') ($sourceUnfundedCommitment * $selectedFraction) 'Excel/Mog selected commitment rights value'
    Assert-Close (Value $other 'B25') $expectedCommitmentAdjustment 'Excel/Mog selected commitment net adjustment'
    $baseOpeningCash = [double](Value $cash 'B17')
    $baseClosingCash = [double](Value $cash 'B18')
    $expectedBaseFunding = if ($baseOpeningCash -lt 0 -or $baseClosingCash -lt 0) { 'UNFUNDED_CASH' } else { 'OK' }
    if ((Value $other 'B26') -ne $expectedBaseFunding) { throw "Excel/Mog base funding status expected $expectedBaseFunding, got $(Value $other 'B26')" }
    Assert-Close (Value $other 'L15') $proof.snapshot.periodEnd.remainingIntangibles 'Excel/Mog FY2036 intangibles'
    Assert-Close (Value $other 'B20') (-$sourceUnfundedCommitment) 'Excel/Mog commitment CFI funding'
    Assert-Close (Value $other 'B23') ([double](Value $inputs 'B267')) 'Excel/Mog unidentified D&A residual'
    Assert-Close (Value $income 'B11') $proof.snapshot.stub.ebit 'Excel/Mog stub EBIT'
    Assert-Close (Value $cash 'B12') $proof.snapshot.stub.cfo 'Excel/Mog stub CFO'
    Assert-Close (Value $dcf 'B7') $proof.snapshot.stub.economicUfcf 'Excel/Mog stub UFCF'
    Assert-Close (Value $dcf 'B9') (([double](Value $cash 'B12')) + ([double](Value $cash 'B13'))) 'Excel cash FCF definition'
    Assert-Close (Value $bs 'B32') 0 'Excel balance difference'
    Assert-Close (Value $other 'L11') $proof.snapshot.otherBalances.investmentValue[10] 'Excel/Mog FY2036 value bridge'
    Assert-Close (Value $income 'L11') $proof.snapshot.periodEnd.ebit 'Excel/Mog FY2036 EBIT'
    Assert-Close (Value $dcf 'L7') $proof.snapshot.periodEnd.economicUfcf 'Excel/Mog FY2036 UFCF'
    Assert-Close (Value $bs 'L11') $proof.snapshot.periodEnd.netPpe 'Excel/Mog FY2036 net PP&E'
    Assert-Close (Value $financing 'L55') $proof.snapshot.periodEnd.financePpe 'Excel/Mog FY2036 finance PP&E'
    Assert-Close (Value $workingCapital 'L41') $proof.snapshot.periodEnd.cashConversionNwc 'Excel/Mog FY2036 cash-conversion NWC'
    Assert-Close (Value $taxes 'L16') $proof.snapshot.periodEnd.currentTaxPayable 'Excel/Mog FY2036 current tax payable'
    Assert-Close (Value $taxes 'L20') $proof.snapshot.periodEnd.longTermTaxLiability 'Excel/Mog FY2036 long-term tax liability'
    Assert-Close (Value $taxes 'L22') $proof.snapshot.periodEnd.deferredTaxLiability 'Excel/Mog FY2036 deferred tax liability'
    $valueFormula = Assert-Formula $other 'B11' 'OtherBalances!B11'
    if (-not [regex]::IsMatch($valueFormula, 'Inputs!B\$234') -or -not [regex]::IsMatch($valueFormula, 'Inputs!B\$268') -or -not [regex]::IsMatch($valueFormula, 'Inputs!B\$269') -or -not [regex]::IsMatch($valueFormula, 'Inputs!B\$270') -or -not [regex]::IsMatch($valueFormula, 'Inputs!B\$238')) { throw "OtherBalances!B11 is not input-linked: $valueFormula" }
    $cashIncomeFormula = Assert-Formula $other 'B8' 'OtherBalances!B8'
    if (-not $cashIncomeFormula.Contains('MAX(0') -or -not $cashIncomeFormula.Contains('Inputs!B$277')) { throw "OtherBalances!B8 is not negative-cash/eligible-pool linked: $cashIncomeFormula" }
    $nextCashIncomeFormula = Assert-Formula $other 'C8' 'OtherBalances!C8'
    if (-not $nextCashIncomeFormula.Contains('MAX(0') -or -not $nextCashIncomeFormula.Contains('CashFlow!B18')) { throw "OtherBalances!C8 is not linked to prior CashFlow closing cash: $nextCashIncomeFormula" }
    $fundingFormula = Assert-Formula $other 'B26' 'OtherBalances!B26'
    if (-not $fundingFormula.Contains('CashFlow!B18')) { throw "OtherBalances!B26 is not linked to current CashFlow closing cash: $fundingFormula" }
    $nextFundingFormula = Assert-Formula $other 'C26' 'OtherBalances!C26'
    if (-not $nextFundingFormula.Contains('CashFlow!B18') -or -not $nextFundingFormula.Contains('CashFlow!C18')) { throw "OtherBalances!C26 is not linked to actual opening/current CashFlow cash: $nextFundingFormula" }
    $eligibleNoncashPool = [double](Value $inputs 'B243') + [double](Value $inputs 'B277') + [double](Value $inputs 'B245')
    $baseYield = [double](Value $inputs 'B235')
    $baseNextCashIncome = [double](Value $other 'C8')
    $columns = @('B','C','D','E','F','G','H','I','J','K','L')
    for ($index = 0; $index -lt $columns.Count; $index++) {
        $column = $columns[$index]
        $opening = [double](Value $cash "${column}17")
        $closing = [double](Value $cash "${column}18")
        $expectedOpening = if ($index -eq 0) { [double](Value $inputs 'B242') } else { [double](Value $cash "$($columns[$index - 1])18") }
        Assert-Close $opening $expectedOpening "CashFlow ${column}17 actual opening cash"
        $days = [double](Value $inputs "${column}278")
        $expectedIncome = ([math]::Max($opening, 0.0) + $eligibleNoncashPool) * $baseYield * $days / 365.0
        Assert-Close (Value $other "${column}8") $expectedIncome "OtherBalances ${column}8 actual cash income"
        $expectedStatus = if ($opening -lt 0 -or $closing -lt 0) { 'UNFUNDED_CASH' } else { 'OK' }
        if ([string](Value $other "${column}26") -ne $expectedStatus) { throw "OtherBalances ${column}26 expected $expectedStatus, got $(Value $other "${column}26")" }
    }

    $baseCapexRate = [double](Value $inputs 'B32')
    $inputs.Range('B32').Value2 = [double]0.8
    Recalculate $excel
    Assert-Changed (Value $cash 'B18') $baseClosingCash 'Capex-rate stress closing cash'
    if ([double](Value $cash 'B18') -ge 0) { throw 'Capex-rate stress did not produce negative closing cash' }
    if ((Value $other 'B26') -ne 'UNFUNDED_CASH') { throw 'Capex-rate stress did not flag UNFUNDED_CASH' }
    $stressIncome = [double](Value $other 'C8')
    Assert-Changed $stressIncome $baseNextCashIncome 'Earlier cash-flow edit changes later cash income'
    $stressDays = [double](Value $inputs 'C278')
    Assert-Close $stressIncome ($eligibleNoncashPool * $baseYield * $stressDays / 365.0) 'Negative prior closing cash earns no yield'
    $inputs.Range('B32').Value2 = $baseCapexRate
    Recalculate $excel
    if ((Value $inputs 'B253') -ne 'PASS' -or (Value $checks 'B22') -ne 'PASS') { throw 'Capex-rate stress recovery did not restore P8D gate' }
    $cashFcfFormula = Assert-Formula $dcf 'B9' 'DCF!B9 cash FCF'
    if (-not $cashFcfFormula.Contains('CashFlow!B12') -or -not $cashFcfFormula.Contains('CashFlow!B13')) { throw "DCF!B9 is not CFO minus cash PP&E payments: $cashFcfFormula" }

    $baseMultiplier = [double](Value $inputs 'B234')
    $baseValue = [double](Value $other 'B11')
    $baseEquity = [double](Value $dcf 'B22')
    $multiplierEdit = if ($baseMultiplier -le 1.0) { 1.5 } else { 0.5 }
    $inputs.Range('B234').Value2 = [double]$multiplierEdit
    Recalculate $excel
    Assert-Close (Value $other 'B11') ($baseValue + $sourceOtherInvestmentPool * ($multiplierEdit - $baseMultiplier)) 'Multiplier value bridge movement'
    Assert-Close (Value $dcf 'B22') ($baseEquity + $sourceOtherInvestmentPool * ($multiplierEdit - $baseMultiplier)) 'Multiplier equity bridge movement'
    if ((Value $review 'B3') -ne 'EDITED_UNREVIEWED') { throw 'Multiplier edit did not invalidate review binding' }
    $inputs.Range('B234').Value2 = $baseMultiplier
    Recalculate $excel
    if ((Value $inputs 'B253') -ne 'PASS' -or (Value $checks 'B22') -ne 'PASS') { throw 'Multiplier recovery did not restore P8D gate' }

    $baseYield = [double](Value $inputs 'B235')
    $baseIncome = [double](Value $other 'B8')
    $baseNetIncome = [double](Value $income 'B15')
    $baseCfo = [double](Value $cash 'B12')
    $baseUfcf = [double](Value $dcf 'B7')
    $baseDeferredTax = [double](Value $taxes 'B22')
    $inputs.Range('B235').Value2 = [double]($baseYield + 0.01)
    Recalculate $excel
    Assert-Changed (Value $other 'B8') $baseIncome 'Yield cash-income propagation'
    Assert-Changed (Value $income 'B15') $baseNetIncome 'Yield net-income propagation'
    Assert-Changed (Value $cash 'B12') $baseCfo 'Yield CFO propagation'
    Assert-Close (Value $dcf 'B7') $baseUfcf 'Yield UFCF exclusion'
    $inputs.Range('B235').Value2 = $baseYield
    Recalculate $excel

    $baseTail = [double](Value $inputs 'B236')
    $tailPool = [double](Value $inputs 'B276')
    $inputs.Range('B236').Value2 = [double]6
    Recalculate $excel
    Assert-Close (Value $other 'L15') ($tailPool * [math]::Max(6 - 6, 0) / 6) 'Six-year tail run-off'
    $inputs.Range('B236').Value2 = [double]15
    Recalculate $excel
    Assert-Close (Value $other 'L15') ($tailPool * [math]::Max(15 - 6, 0) / 15) 'Fifteen-year tail remaining balance'
    $inputs.Range('B236').Value2 = $baseTail
    Recalculate $excel

    $baseGain = [double](Value $inputs 'B241')
    $gainEdit = if ($baseGain -eq 0) { [double]14 } else { [double]0 }
    $inputs.Range('B241').Value2 = [double]$gainEdit
    Recalculate $excel
    Assert-Changed (Value $income 'B15') $baseNetIncome 'Gain net-income propagation'
    Assert-Close (Value $cash 'B12') $baseCfo 'Gain CFO neutrality'
    Assert-Close (Value $dcf 'B7') $baseUfcf 'Gain UFCF neutrality'
    Assert-Changed (Value $taxes 'B22') $baseDeferredTax 'Gain deferred-tax propagation'
    $inputs.Range('B241').Value2 = $baseGain
    Recalculate $excel

    $baseFraction = [double](Value $inputs 'B238')
    $baseRights = [double](Value $other 'B24')
    $baseAdjustment = [double](Value $other 'B25')
    $baseBridge = [double](Value $other 'B11')
    $fractionEdit = if ($baseFraction -eq 0) { 1 } else { 0 }
    $inputs.Range('B238').Value2 = [double]$fractionEdit
    Recalculate $excel
    $expectedAdjustment = $sourceUnfundedCommitment * ($fractionEdit - 1) / [math]::Pow(1.043, 91.0 / 365.0)
    Assert-Close (Value $other 'B24') ($sourceUnfundedCommitment * $fractionEdit) 'Edited commitment rights value'
    Assert-Close (Value $other 'B25') $expectedAdjustment 'Edited commitment adjustment'
    Assert-Close (Value $other 'B11') ($baseBridge + $expectedAdjustment - $baseAdjustment) 'Edited commitment bridge movement'
    Assert-Changed (Value $other 'B24') $baseRights 'Commitment rights propagation'
    Assert-Changed (Value $other 'B25') $baseAdjustment 'Commitment adjustment propagation'
    Assert-Changed (Value $other 'B11') $baseBridge 'Commitment bridge propagation'
    Assert-Close (Value $cash 'B12') $baseCfo 'Commitment valuation CFO neutrality'
    Assert-Close (Value $dcf 'B7') $baseUfcf 'Commitment valuation UFCF neutrality'
    $inputs.Range('B238').Value2 = $baseFraction
    Recalculate $excel
    Assert-Close (Value $other 'B24') $baseRights 'Commitment rights recovery'
    Assert-Close (Value $other 'B25') $baseAdjustment 'Commitment adjustment recovery'

    $inputs.Range('B234').ClearContents()
    Recalculate $excel
    if ((Value $inputs 'B253') -ne 'FAIL' -or (Value $dcf 'B18') -ne 'BLOCKED') { throw 'Missing multiplier was not blocked' }
    $inputs.Range('B234').Value2 = $baseMultiplier
    Recalculate $excel
    if ((Value $inputs 'B253') -ne 'PASS' -or (Value $checks 'B22') -ne 'PASS') { throw 'Missing multiplier recovery failed' }

    $book.Close($false)
    $book = $null
    $excel.Quit()
    $excel = $null
    $publishedAfter = Sha256 $fullWorkbook
    if ($publishedBefore -ne $publishedAfter) { throw 'Published workbook bytes changed during private Excel proof' }
    $result = [ordered]@{
        status = 'PASS'
        mode = 'native invisible Excel P8D recalculation plus linked control and missing-input guards'
        publishedSha256Before = $publishedBefore
        publishedSha256After = $publishedAfter
        workbookPath = $fullWorkbook
        checks = @('Mog fingerprint and base values match', 'Checks B20:L20 and P8D coverage all PASS', 'FY2036 calculated snapshot matches exported Mog verification', 'all-period actual CashFlow opening/closing cash and eligible income links tie independently', 'cash-flow capex stress produces negative cash, UNFUNDED_CASH and changed next-period income', 'editable multiplier, yield, tail, gain and commitment controls propagate through linked formulas', 'cash FCF remains CFO less cash PP&E payments', 'missing multiplier FAIL/BLOCKED and recovery', 'published bytes preserved')
    }
    $result | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $fullResults -Encoding utf8
    Write-Output ($result | ConvertTo-Json -Depth 8)
} finally {
    if ($book -ne $null) { $book.Close($false) }
    if ($excel -ne $null) { $excel.Quit() }
    Remove-Item -LiteralPath $working -Force -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath $privateDirectory -Recurse -Force -ErrorAction SilentlyContinue
}
