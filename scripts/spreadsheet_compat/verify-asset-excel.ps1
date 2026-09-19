param(
    [Parameter(Mandatory = $true)][string]$WorkbookPath,
    [Parameter(Mandatory = $true)][string]$ResultsPath
)

$ErrorActionPreference = 'Stop'
$tolerance = 1e-8
$fullWorkbook = [System.IO.Path]::GetFullPath($WorkbookPath)
$fullResults = [System.IO.Path]::GetFullPath($ResultsPath)
$working = Join-Path ([System.IO.Path]::GetDirectoryName($fullWorkbook)) 'excel-asset-working-copy.xlsx'
$proofPath = Join-Path ([System.IO.Path]::GetDirectoryName($fullWorkbook)) 'asset-verification.json'
$mogProof = Get-Content -LiteralPath $proofPath -Raw | ConvertFrom-Json

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

[System.IO.File]::Copy($fullWorkbook, $working, $true)
$publishedBefore = Sha256 $fullWorkbook
if ($publishedBefore -ne $mogProof.publishedSha256) { throw 'Mog verification does not match this workbook fingerprint' }
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
    $excel.Iteration = $false
    $excel.CalculateFullRebuild()
    $inputs = $book.Worksheets.Item('Inputs')
    $schedules = $book.Worksheets.Item('Schedules')
    $income = $book.Worksheets.Item('Income')
    $cash = $book.Worksheets.Item('CashFlow')
    $bs = $book.Worksheets.Item('BalanceSheet')
    $dcf = $book.Worksheets.Item('DCF')
    $checks = $book.Worksheets.Item('Checks')
    $sensitivity = $book.Worksheets.Item('Sensitivity')
    $review = $book.Worksheets.Item('Review')
    $base = [ordered]@{
        stubRevenue = Value $income 'B6'
        openingAssetDepreciation = Value $schedules 'B15'
        newAdditionDepreciation = Value $schedules 'B16'
        totalDepreciation = Value $schedules 'B17'
        cashPpePayments = Value $schedules 'B12'
        noncashPpeAdditions = Value $schedules 'B13'
        recognizedPpeAdditions = Value $schedules 'B14'
        netIncome = Value $income 'B15'
        cfo = Value $cash 'B9'
        cashFcf = Value $dcf 'B9'
        economicUfcf = Value $dcf 'B7'
        closingCash = Value $cash 'B15'
        closingNetPpe = Value $bs 'B11'
        balanceDifference = Value $bs 'B25'
        dcfStatus = Value $dcf 'B24'
        enterpriseValue = Value $dcf 'B18'
        sensitivityCenter = Value $sensitivity 'C5'
        annualRevenue = Value $income 'C6'
    }
    Assert-Close $base.balanceDifference 0 'Excel base balance difference'
    if ($base.dcfStatus -ne $mogProof.snapshot.dcfStatus) { throw "Excel/Mog status mismatch: $($base.dcfStatus)" }
    foreach ($name in @('stubRevenue','openingAssetDepreciation','newAdditionDepreciation','totalDepreciation','cashPpePayments','noncashPpeAdditions','recognizedPpeAdditions','netIncome','cfo','cashFcf','economicUfcf','closingCash','closingNetPpe')) {
        $expectedName = if ($name -eq 'stubRevenue') { 'revenue' } else { $name }
        Assert-Close $base[$name] $mogProof.snapshot.stub.$expectedName "Excel/Mog $name"
    }
    Assert-Close $base.enterpriseValue $mogProof.snapshot.enterpriseValue 'Excel/Mog enterprise value'
    Assert-Close $base.sensitivityCenter $base.enterpriseValue 'Excel sensitivity center'
    Assert-Close $base.annualRevenue $mogProof.snapshot.annualRevenue 'Excel annualized revenue'
    Assert-Close (Value $dcf 'B16') ((Value $dcf 'B15') * (Value $dcf 'L10')) 'Excel terminal discount'
    Assert-Close ($base.cashFcf - $base.economicUfcf) $base.noncashPpeAdditions 'Excel cash/noncash difference'
    if ($null -eq $inputs.Range('B29').Comment -or [string]::IsNullOrWhiteSpace($inputs.Range('B29').Comment.Text())) { throw 'Source/assumption note was lost' }
    foreach ($column in @('B','C','D','E','F','G','H','I','J','K','L')) {
        if ((Value $checks "${column}20") -ne 'PASS') { throw "Excel check failed at ${column}20" }
    }
    $formulas = [ordered]@{
        ppe = Assert-Formula $schedules 'B23' 'Schedules!B23'
        income = Assert-Formula $income 'B11' 'Income!B11'
        cash = Assert-Formula $cash 'B15' 'CashFlow!B15'
        dcf = Assert-Formula $dcf 'B7' 'DCF!B7'
        sensitivity = Assert-Formula ($book.Worksheets.Item('Sensitivity')) 'B4' 'Sensitivity!B4'
    }
    $baseRate = [double]$inputs.Range('B32').Value2
    $inputs.Range('B32').Value2 = $baseRate * 0.8
    $excel.CalculateFullRebuild()
    $editedCapex = Value $schedules 'B12'
    if ([math]::Abs(([double]$editedCapex) - ([double]$base.cashPpePayments * 0.8)) -gt $tolerance) { throw 'Excel editable cash PP&E rate did not propagate' }
    if ([double](Value $bs 'B25') -gt $tolerance -or [double](Value $bs 'B25') -lt -$tolerance) { throw 'Excel edit broke balance sheet' }
    if ((Value $review 'B3') -ne 'EDITED_UNREVIEWED') { throw 'Excel edit falsely retained prior review status' }
    Assert-Close (Value $sensitivity 'C5') (Value $dcf 'B18') 'Excel edited sensitivity center'
    $inputs.Range('B32').Value2 = $baseRate
    $excel.CalculateFullRebuild()
    $restoredCapex = Value $schedules 'B12'
    Assert-Close $restoredCapex $base.cashPpePayments 'Excel restored cash PP&E payment'
    $baseLife = [double]$inputs.Range('B29').Value2
    $inputs.Range('B29').Value2 = $baseLife + 2
    $excel.CalculateFullRebuild()
    $lifeEdit = [ordered]@{ depreciation = Value $schedules 'B17'; netIncome = Value $income 'B15'; cfo = Value $cash 'B9' }
    if ($lifeEdit.depreciation -ge $base.totalDepreciation -or $lifeEdit.netIncome -le $base.netIncome -or $lifeEdit.cfo -ge $base.cfo) { throw 'Excel life edit failed depreciation/profit/tax-shield directions' }
    $inputs.Range('B29').Value2 = $baseLife
    $excel.CalculateFullRebuild()
    foreach ($address in @('B32','B33','L55')) {
        $original = $inputs.Range($address).Formula
        $inputs.Range($address).ClearContents()
        $excel.CalculateFullRebuild()
        if ((Value $checks 'B22') -ne 'FAIL') { throw "Excel missing $address did not fail global gate" }
        foreach ($cell in @('B14','B15','B16','B17','B18','B22')) {
            if ((Value $dcf $cell) -ne 'BLOCKED') { throw "Excel missing $address left valuation $cell unblocked" }
        }
        $inputs.Range($address).Formula = $original
        $excel.CalculateFullRebuild()
    }
    $lastDifferenceFormula = $bs.Range('L25').Formula
    $bs.Range('L25').Value2 = 1
    $excel.CalculateFullRebuild()
    if ((Value $checks 'B20') -ne 'PASS' -or (Value $checks 'L20') -ne 'FAIL' -or (Value $dcf 'B18') -ne 'BLOCKED') { throw 'Excel last-period failure did not block DCF' }
    $bs.Range('L25').Formula = $lastDifferenceFormula
    $baseNoncash = $inputs.Range('B33').Value2
    $inputs.Range('B33').Value2 = 0
    $excel.CalculateFullRebuild()
    if ((Value $checks 'B22') -ne 'PASS') { throw 'Excel rejected numeric zero' }
    Assert-Close (Value $dcf 'B7') (Value $dcf 'B9') 'Excel explicit zero financing difference'
    $inputs.Range('B33').Value2 = $baseNoncash
    $excel.CalculateFullRebuild()
    Assert-Close (Value $dcf 'B18') $base.enterpriseValue 'Excel complete recovery'
    $book.Close($false)
    $book = $null
    $excel.Quit()
    $excel = $null
    $result = [ordered]@{
        status = 'PASS'
        mode = 'native invisible Excel recalculation plus editable-input readback'
        publishedSha256Before = $publishedBefore
        publishedSha256After = Sha256 $fullWorkbook
        workbookPath = $fullWorkbook
        base = $base
        editedCashPpePayments = $editedCapex
        restoredCashPpePayments = $restoredCapex
        lifeEdit = $lifeEdit
        formulas = $formulas
        checks = @('Mog fingerprint and values match', 'B20:L20 all PASS', 'cash/noncash separation including zero', 'life/profit/cash-tax sensitivity', 'live scenario center tie', 'missing input blocked', 'last-period failure blocked', 'edited review status', 'source note retained', 'recovery and published bytes preserved')
    }
    $result | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $fullResults -Encoding utf8
    Write-Output ($result | ConvertTo-Json -Depth 8)
} finally {
    if ($book -ne $null) { $book.Close($false) }
    if ($excel -ne $null) { $excel.Quit() }
    Remove-Item -LiteralPath $working -Force -ErrorAction SilentlyContinue
}
