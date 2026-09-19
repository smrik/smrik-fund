param(
    [Parameter(Mandatory = $true)][string]$WorkbookPath,
    [Parameter(Mandatory = $true)][string]$ResultsPath,
    [ValidateSet('OFFLINE_FIXTURE', 'REVIEW_REQUIRED', 'UNREVIEWED_PROVISIONAL', 'SYSTEM_REVIEWED_PROVISIONAL')]
    [string]$ExpectedStatus = 'OFFLINE_FIXTURE'
)

$ErrorActionPreference = 'Stop'
$tolerance = 1e-8
$fullWorkbook = [System.IO.Path]::GetFullPath($WorkbookPath)
$fullResults = [System.IO.Path]::GetFullPath($ResultsPath)
$dir = [System.IO.Path]::GetDirectoryName($fullWorkbook)
$working = Join-Path $dir 'excel-p6-working-copy.xlsx'
$proof = Get-Content -LiteralPath (Join-Path $dir 'asset-verification.json') -Raw | ConvertFrom-Json
function Value($sheet, [string]$address) { $v = $sheet.Range($address).Value2; if ($null -eq $v) { return $null }; return [double]$v }
function Close($a, $b, [string]$label) { if ($null -eq $a -or $null -eq $b -or [math]::Abs(([double]$a) - ([double]$b)) -gt $tolerance) { throw "$label expected $b got $a" } }
function Formula($sheet, [string]$address, [string]$label) { $f = [string]$sheet.Range($address).Formula; if (-not $f.StartsWith('=')) { throw "$label lost formula" }; return $f }
function Changed($sheet, [string]$address, [double]$before, [string]$label) { if ([math]::Abs((Value $sheet $address) - $before) -le $tolerance) { throw "$label did not change at $address" } }
[System.IO.File]::Copy($fullWorkbook, $working, $true)
$excel = $null; $book = $null
try {
    $excel = New-Object -ComObject Excel.Application
    $excel.Visible = $false; $excel.DisplayAlerts = $false; $excel.ScreenUpdating = $false; $excel.EnableEvents = $false; $excel.AutomationSecurity = 3
    $book = $excel.Workbooks.Open($working, 0, $false); $excel.Iteration = $false; $excel.CalculateFullRebuild()
    $inputs = $book.Worksheets.Item('Inputs'); $operating = $book.Worksheets.Item('Operating'); $schedules = $book.Worksheets.Item('Schedules'); $income = $book.Worksheets.Item('Income'); $cash = $book.Worksheets.Item('CashFlow'); $bs = $book.Worksheets.Item('BalanceSheet'); $dcf = $book.Worksheets.Item('DCF'); $checks = $book.Worksheets.Item('Checks')
    $base = [ordered]@{ revenue = Value $income 'B6'; grossCosts = Value $operating 'B17'; embeddedPpeRemoved = Value $operating 'B18'; scheduledPpeAdded = Value $operating 'B19'; totalExpenses = Value $operating 'B20'; ebit = Value $income 'B11'; depreciation = Value $schedules 'B17'; netIncome = Value $income 'B15'; cfo = Value $cash 'B9'; cashFcf = Value $dcf 'B9'; economicUfcf = Value $dcf 'B7'; closingCash = Value $cash 'B15'; closingNetPpe = Value $bs 'B11'; balanceDifference = Value $bs 'B25'; enterpriseValue = Value $dcf 'B18'; status = [string]$dcf.Range('B24').Value2 }
    if ($base.status -ne $ExpectedStatus) { throw "Base status expected $ExpectedStatus got $($base.status)" }
    Close ($base.grossCosts - $base.embeddedPpeRemoved + $base.scheduledPpeAdded) $base.totalExpenses 'Excel P6 expense bridge'; Close ($base.revenue - $base.totalExpenses) $base.ebit 'Excel P6 EBIT bridge'
    Close $base.balanceDifference 0 'Excel balance'; Close $base.revenue $proof.snapshot.stub.revenue 'Excel/Mog revenue'; Close $base.depreciation $proof.snapshot.stub.totalDepreciation 'Excel/Mog depreciation'; Close $base.netIncome $proof.snapshot.stub.netIncome 'Excel/Mog net income'; Close $base.cfo $proof.snapshot.stub.cfo 'Excel/Mog CFO'; Close $base.cashFcf $proof.snapshot.stub.cashFcf 'Excel/Mog cash FCF'; Close $base.economicUfcf $proof.snapshot.stub.economicUfcf 'Excel/Mog economic UFCF'; Close $base.closingCash $proof.snapshot.stub.closingCash 'Excel/Mog closing cash'; Close $base.closingNetPpe $proof.snapshot.stub.closingNetPpe 'Excel/Mog closing PP&E'; Close $base.enterpriseValue $proof.snapshot.enterpriseValue 'Excel/Mog EV'
    foreach ($col in @('B','C','D','E','F','G','H','I','J','K','L')) { if (([string]$checks.Range("${col}20").Value2) -ne 'PASS') { throw "Excel check failed ${col}20" } }
    $formulas = [ordered]@{ segmentStub = Formula $operating 'B6' 'Operating!B6'; segmentNextYear = Formula $operating 'C6' 'Operating!C6'; costOfRevenue = Formula $operating 'B13' 'Operating!B13'; operatingRevenue = Formula $operating 'B11' 'Operating!B11'; schedules = Formula $schedules 'B23' 'Schedules!B23'; income = Formula $income 'B11' 'Income!B11'; dcf = Formula $dcf 'B7' 'DCF!B7' }
    $growthAddress = 'B64'; $growthBase = Value $inputs $growthAddress
    $growthRevenueBase = [ordered]@{ B6 = Value $operating 'B6'; C6 = Value $operating 'C6' }
    $growthCostBase = [ordered]@{ B13 = Value $operating 'B13'; B14 = Value $operating 'B14'; B15 = Value $operating 'B15'; B16 = Value $operating 'B16'; C13 = Value $operating 'C13'; C14 = Value $operating 'C14'; C15 = Value $operating 'C15'; C16 = Value $operating 'C16' }
    $growthDownstreamBase = [ordered]@{ B12 = Value $schedules 'B12'; C12 = Value $schedules 'C12'; B17 = Value $schedules 'B17'; C17 = Value $schedules 'C17'; B11 = Value $income 'B11'; C11 = Value $income 'C11'; B15 = Value $income 'B15'; C15 = Value $income 'C15'; B9 = Value $cash 'B9'; C9 = Value $cash 'C9'; B15Cash = Value $cash 'B15'; C15Cash = Value $cash 'C15'; B11Ppe = Value $bs 'B11'; C11Ppe = Value $bs 'C11'; B7 = Value $dcf 'B7'; C7 = Value $dcf 'C7' }
    $inputs.Range($growthAddress).Value2 = $growthBase + 0.01; $excel.CalculateFullRebuild()
    foreach ($a in $growthRevenueBase.Keys) { Changed $operating $a $growthRevenueBase[$a] 'Growth driver segment revenue' }
    foreach ($a in $growthCostBase.Keys) { Changed $operating $a $growthCostBase[$a] 'Growth driver operating cost' }
    foreach ($a in @('B12','C12')) { Changed $schedules $a $growthDownstreamBase[$a] 'Growth driver capex' }
    foreach ($a in @('B17','C17')) { Changed $schedules $a $growthDownstreamBase[$a] 'Growth driver depreciation' }
    foreach ($a in @('B11','C11','B15','C15')) { Changed $income $a $growthDownstreamBase[$a] 'Growth driver income' }
    foreach ($a in @('B9','C9')) { Changed $cash $a $growthDownstreamBase[$a] 'Growth driver CFO' }
    Changed $cash 'B15' $growthDownstreamBase.B15Cash 'Growth driver closing cash'; Changed $cash 'C15' $growthDownstreamBase.C15Cash 'Growth driver closing cash'
    Changed $bs 'B11' $growthDownstreamBase.B11Ppe 'Growth driver closing PP&E'; Changed $bs 'C11' $growthDownstreamBase.C11Ppe 'Growth driver closing PP&E'
    Changed $dcf 'B7' $growthDownstreamBase.B7 'Growth driver DCF'; Changed $dcf 'C7' $growthDownstreamBase.C7 'Growth driver DCF'
    if (([string]$book.Worksheets.Item('Review').Range('B3').Value2) -ne 'EDITED_UNREVIEWED') { throw 'Growth driver did not set EDITED_UNREVIEWED' }
    $inputs.Range($growthAddress).Value2 = $growthBase; $excel.CalculateFullRebuild()
    $costAddress = 'B68'; $costRatioBase = Value $inputs $costAddress; $costBase = Value $operating 'B13'; $inputs.Range($costAddress).Value2 = $costRatioBase + 0.01; $excel.CalculateFullRebuild(); Changed $operating 'B13' $costBase 'Cost-ratio edit cost of revenue'; Changed $income 'B11' $base.ebit 'Cost-ratio edit EBIT'; Changed $income 'B15' $base.netIncome 'Cost-ratio edit net income'; $inputs.Range($costAddress).Value2 = $costRatioBase; $excel.CalculateFullRebuild()
    $life = [double]$inputs.Range('B29').Value2; $inputs.Range('B29').Value2 = $life + 2; $excel.CalculateFullRebuild(); $lifeChanged = [ordered]@{ depreciation = Value $schedules 'B17'; ebit = Value $income 'B11'; netIncome = Value $income 'B15'; cfo = Value $cash 'B9'; closingCash = Value $cash 'B15' }; if (([math]::Abs($lifeChanged.depreciation - $base.depreciation)) -le $tolerance) { throw 'Asset-life edit did not change PP&E depreciation' }; if (([math]::Abs($lifeChanged.ebit - $base.ebit)) -le $tolerance) { throw 'Asset-life edit did not change EBIT' }; if (([math]::Abs($lifeChanged.netIncome - $base.netIncome)) -le $tolerance) { throw 'Asset-life edit did not change net income' }; if (([math]::Abs($lifeChanged.cfo - $base.cfo)) -le $tolerance) { throw 'Asset-life edit did not change CFO' }; if (([math]::Abs($lifeChanged.closingCash - $base.closingCash)) -le $tolerance) { throw 'Asset-life edit did not change closing cash' }; $inputs.Range('B29').Value2 = $life; $excel.CalculateFullRebuild()
    $beforeBytes = [System.IO.File]::ReadAllBytes($fullWorkbook); $inputs.Range($growthAddress).ClearContents(); $excel.CalculateFullRebuild(); if (([string]$inputs.Range('B54').Value2) -ne 'FAIL' -or ([string]$inputs.Range('B78').Value2) -ne 'FAIL' -or ([string]$checks.Range('B22').Value2) -ne 'FAIL' -or ([string]$dcf.Range('B18').Value2) -ne 'BLOCKED') { throw 'Missing P6 growth driver did not block' }; $inputs.Range($growthAddress).Value2 = 0; $excel.CalculateFullRebuild(); if (([string]$inputs.Range('B54').Value2) -ne 'PASS' -or ([string]$inputs.Range('B78').Value2) -ne 'PASS') { throw 'Numeric zero P6 growth driver did not recover' }; $inputs.Range($growthAddress).Value2 = $growthBase; $excel.CalculateFullRebuild()
    foreach ($a in @('B32','B33','L55')) { $original = $inputs.Range($a).Formula; $inputs.Range($a).ClearContents(); $excel.CalculateFullRebuild(); if (([string]$checks.Range('B22').Value2) -ne 'FAIL' -or ([string]$dcf.Range('B18').Value2) -ne 'BLOCKED') { throw "Missing $a did not block" }; $inputs.Range($a).Formula = $original; $excel.CalculateFullRebuild() }
    $hashAfter = [System.IO.File]::ReadAllBytes($fullWorkbook); if (-not [System.Linq.Enumerable]::SequenceEqual($beforeBytes, $hashAfter)) { throw 'Published workbook bytes changed' }
    $book.Close($false); $book = $null; $excel.Quit(); $excel = $null
    [ordered]@{ status = 'PASS'; mode = 'native invisible Excel recalculation plus P6 driver edits'; expectedStatus = $ExpectedStatus; workbookPath = $fullWorkbook; base = $base; lifeSensitivity = $lifeChanged; formulas = $formulas; checks = @('Mog/Excel values match','B20:L20 all PASS','P6 gross-minus-embedded-plus-scheduled bridge ties','growth driver reaches current/later revenue, costs, capex, depreciation, profit, cash, PP&E and DCF','cost-ratio driver changes expense and profit','asset-life edit changes depreciation, EBIT, tax, NI, CFO and cash','missing growth driver blocked and numeric zero recovered','published bytes preserved') } | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $fullResults -Encoding utf8
    Get-Content -LiteralPath $fullResults -Raw
} finally { if ($book -ne $null) { $book.Close($false) }; if ($excel -ne $null) { $excel.Quit() }; Remove-Item -LiteralPath $working -Force -ErrorAction SilentlyContinue }
