param(
    [Parameter(Mandatory = $true)][string]$WorkbookPath,
    [Parameter(Mandatory = $true)][string]$ResultsPath
)

$ErrorActionPreference = 'Stop'
$tolerance = 0.00001
$fullWorkbook = [System.IO.Path]::GetFullPath($WorkbookPath)
$fullResults = [System.IO.Path]::GetFullPath($ResultsPath)
$proofPath = Join-Path ([System.IO.Path]::GetDirectoryName($fullWorkbook)) 'p9-verification.json'
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
    if ($null -eq $actual -or $actual -is [string]) { throw "$label is missing or nonnumeric" }
    if ([math]::Abs(([double]$actual) - ([double]$expected)) -gt $tolerance) { throw "$label expected $expected, got $actual" }
}
function Assert-Changed($actual, $baseline, [string]$label) {
    if ($null -eq $actual -or $actual -is [string]) { throw "$label is missing or nonnumeric" }
    if ([math]::Abs(([double]$actual) - ([double]$baseline)) -le $tolerance) { throw "$label did not change" }
}
function Assert-Formula($sheet, [string]$address, [string]$label) {
    $formula = [string]$sheet.Range($address).Formula
    if (-not $formula.StartsWith('=')) { throw "$label lost formula: $formula" }
    return $formula
}
function Recalculate($excel) {
    $excel.CalculateFullRebuild()
    Start-Sleep -Milliseconds 300
}

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
    $book.ForceFullCalculation = $true
    Recalculate $excel

    $inputs = $book.Worksheets.Item('Inputs')
    $valuation = $book.Worksheets.Item('Valuation')
    $cohorts = $book.Worksheets.Item('TerminalCohorts')
    $sensitivity = $book.Worksheets.Item('P9Sensitivity')
    $income = $book.Worksheets.Item('Income')
    $other = $book.Worksheets.Item('OtherBalances')
    $review = $book.Worksheets.Item('Review')
    $dcf = $book.Worksheets.Item('DCF')
    $equity = $book.Worksheets.Item('Equity')

    if ((Value $valuation 'B3') -ne 'PROVISIONAL_REVIEW_REQUIRED') { throw 'Excel base review status failed' }
    Assert-Formula $valuation 'B41' 'Attached review comparison' | Out-Null
    foreach ($address in @('B40','B79','B97','B99')) { if ((Value $valuation $address) -ne 'PASS') { throw "Excel valuation gate failed at $address" } }
    Assert-Close (Value $valuation 'B39') $proof.snapshot.p9.wacc 'Excel/Mog WACC'
    Assert-Close (Value $valuation 'B50') $proof.snapshot.p9.explicitPv 'Excel/Mog explicit PV'
    Assert-Close (Value $valuation 'B57') $proof.snapshot.p9.terminal.openingCapital 'Excel/Mog terminal opening capital'
    Assert-Close (Value $valuation 'B66') $proof.snapshot.p9.terminal.grossAdditions 'Excel/Mog terminal gross additions'
    Assert-Close (Value $valuation 'B69') $proof.snapshot.p9.terminal.depreciation 'Excel/Mog terminal depreciation'
    Assert-Close (Value $valuation 'B76') $proof.snapshot.p9.terminal.ufcf 'Excel/Mog terminal UFCF'
    Assert-Close (Value $valuation 'B120') $proof.snapshot.p9.enterpriseValue 'Excel/Mog enterprise value'
    Assert-Close (Value $valuation 'B121') $proof.snapshot.p9.commonEquityValue 'Excel/Mog common equity value'
    Assert-Close (Value $valuation 'B122') $proof.snapshot.p9.perShareValue 'Excel/Mog per-share value'
    Assert-Close (Value $valuation 'B109') $proof.snapshot.p9.taxTimingPv 'Excel/Mog tax timing diagnostic'
    Assert-Close (Value $valuation 'B113') $proof.snapshot.p9.supplierClosing 'Excel/Mog supplier payable limitation'
    Assert-Close (Value $cohorts 'E44') 3.833056375016537 'Excel/Mog owned cohort coefficient'
    Assert-Close (Value $cohorts 'K44') 6.479456842626223 'Excel/Mog finance cohort coefficient'
    if ((Value $other 'L15') -ne 0) { throw 'Excel finite acquired intangibles did not run off by FY2036' }
    Assert-Close (Value $dcf 'B18') $proof.snapshot.p9.enterpriseValue 'Canonical DCF enterprise value'
    Assert-Close (Value $dcf 'B27') $proof.snapshot.p9.commonEquityValue 'Canonical DCF common equity value'
    Assert-Close (Value $dcf 'B29') $proof.snapshot.p9.perShareValue 'Canonical DCF per-share value'

    $waccFormula = Assert-Formula $valuation 'B39' 'Valuation!B39'
    if (-not $waccFormula.Contains('B34/(B34+B35)') -or -not $waccFormula.Contains('B35/(B34+B35)')) { throw 'WACC formula lost market weighting' }
    $terminalFormula = Assert-Formula $valuation 'B76' 'Valuation!B76'
    if ($terminalFormula -ne '=B72-B74') { throw "Terminal UFCF formula changed: $terminalFormula" }
    $equityFormula = Assert-Formula $valuation 'B95' 'Valuation!B95'
    foreach ($token in @('B85','B86','B87','B88','B89','B90','B91','B92')) { if (-not $equityFormula.Contains($token)) { throw "Equity bridge lost $token" } }

    Assert-Close (Value $sensitivity 'M4') 2393366.515270386 'Excel zero-growth terminal value'
    Assert-Close (Value $sensitivity 'O4') 207.6535775704229 'Excel zero-growth per share'
    Assert-Close (Value $sensitivity 'N6') $proof.snapshot.p9.enterpriseValue 'Excel terminal sensitivity base EV'
    Assert-Close (Value $sensitivity 'O7') 260.26827413872076 'Excel 3% terminal sensitivity per share'
    Assert-Close (Value $sensitivity 'E12') $proof.snapshot.p9.wacc 'Excel WACC sensitivity center'
    if ([double](Value $sensitivity 'E11') -ge [double](Value $sensitivity 'E12') -or [double](Value $sensitivity 'E13') -le [double](Value $sensitivity 'E12')) { throw 'Excel beta sensitivity is not ordered' }

    $baseGrowth = [double](Value $inputs 'B64')
    $baseRevenue = [double](Value $income 'L6')
    $baseEnterprise = [double](Value $valuation 'B120')
    $inputs.Range('B64').Value2 = $baseGrowth + 0.01
    Recalculate $excel
    Assert-Changed (Value $income 'L6') $baseRevenue 'Operating driver FY2036 revenue'
    Assert-Changed (Value $valuation 'B120') $baseEnterprise 'Operating driver P9 enterprise value'
    if ((Value $valuation 'B41') -ne 'EDITED_UNREVIEWED' -or (Value $review 'B3') -ne 'EDITED_UNREVIEWED') { throw 'Operating edit did not invalidate attached review' }
    $inputs.Range('B64').Value2 = $baseGrowth
    Recalculate $excel
    Assert-Close (Value $valuation 'B120') $baseEnterprise 'Operating driver recovery'

    $basePrice = [double](Value $inputs 'B176')
    $inputs.Range('B176').ClearContents()
    Recalculate $excel
    if ((Value $valuation 'B40') -ne 'FAIL' -or (Value $valuation 'B120') -ne 'BLOCKED' -or (Value $valuation 'B122') -ne 'BLOCKED' -or (Value $valuation 'B3') -ne 'BLOCKED') { throw 'Mandatory missing market input did not block valuation' }
    $inputs.Range('B176').Value2 = $basePrice
    Recalculate $excel
    if ((Value $valuation 'B40') -ne 'PASS' -or (Value $valuation 'B99') -ne 'PASS') { throw 'Mandatory market-input recovery failed' }

    $baseEquity = [double](Value $valuation 'B121')
    $valuation.Range('B24').Value2 = 1.0
    Recalculate $excel
    Assert-Close (Value $valuation 'B121') ($baseEquity - 3563) 'Current-tax face claim once'
    if ((Value $valuation 'B41') -ne 'EDITED_UNREVIEWED') { throw 'Current-tax claim edit did not invalidate review' }
    $valuation.Range('B24').Value2 = 0.0
    Recalculate $excel
    Assert-Close (Value $valuation 'B121') $baseEquity 'Current-tax claim recovery'

    $baseMultiplier = [double](Value $inputs 'B234')
    $inputs.Range('B234').ClearContents()
    Recalculate $excel
    if ((Value $inputs 'B253') -ne 'FAIL' -or (Value $valuation 'B99') -ne 'FAIL' -or (Value $valuation 'B120') -ne 'BLOCKED') { throw 'Upstream P8D gate did not block canonical valuation' }
    $inputs.Range('B234').Value2 = $baseMultiplier
    Recalculate $excel
    if ((Value $inputs 'B253') -ne 'PASS' -or (Value $valuation 'B99') -ne 'PASS') { throw 'Upstream P8D gate recovery failed' }

    $baseOwnedLife = [double](Value $inputs 'B30')
    $baseGross = [double](Value $valuation 'B66')
    $baseDepreciation = [double](Value $valuation 'B69')
    $inputs.Range('B30').Value2 = 9.0
    Recalculate $excel
    Assert-Changed (Value $valuation 'B66') $baseGross 'Upstream owned life terminal gross additions'
    Assert-Changed (Value $valuation 'B69') $baseDepreciation 'Upstream owned life terminal depreciation'
    Assert-Changed (Value $valuation 'B120') $baseEnterprise 'Upstream owned life enterprise value'
    if ((Value $valuation 'B41') -ne 'EDITED_UNREVIEWED') { throw 'Upstream owned-life edit did not invalidate review' }
    $inputs.Range('B30').Value2 = $baseOwnedLife
    Recalculate $excel
    Assert-Close (Value $valuation 'B120') $baseEnterprise 'Upstream owned-life recovery'

    $baseShield = [double](Value $valuation 'B16')
    $valuation.Range('B16').Value2 = 1.5
    Recalculate $excel
    if ((Value $valuation 'B40') -ne 'FAIL' -or (Value $valuation 'B99') -ne 'FAIL' -or (Value $valuation 'B120') -ne 'BLOCKED') { throw 'Invalid tax-shield domain did not block canonical valuation' }
    $valuation.Range('B16').Value2 = $baseShield
    Recalculate $excel
    Assert-Close (Value $valuation 'B120') $baseEnterprise 'Tax-shield domain recovery'

    $book.Close($false)
    $book = $null
    $excel.Quit()
    $excel = $null
    $publishedAfter = Sha256 $fullWorkbook
    if ($publishedBefore -ne $publishedAfter) { throw 'Published workbook bytes changed during private Excel proof' }
    $result = [ordered]@{
        status = 'PASS'
        mode = 'native hidden Excel P9 base/edit/failure/recovery/sensitivity recalculation'
        publishedSha256Before = $publishedBefore
        publishedSha256After = $publishedAfter
        workbookPath = $fullWorkbook
        checks = @('base WACC/terminal/claims/oracles and canonical DCF links', 'terminal g0/g2/g3 and beta sensitivities', 'operating driver propagation and review invalidation', 'missing market input block and recovery', 'current-tax claim once and recovery', 'upstream P8D gate block and recovery', 'upstream terminal-life propagation and recovery', 'invalid financial domain block and recovery', 'published bytes preserved')
    }
    $result | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $fullResults -Encoding utf8
    Write-Output ($result | ConvertTo-Json -Depth 8)
} finally {
    if ($book -ne $null) { $book.Close($false) }
    if ($excel -ne $null) { $excel.Quit() }
    if (Test-Path -LiteralPath $working) { Remove-Item -LiteralPath $working -Force -ErrorAction SilentlyContinue }
    if (Test-Path -LiteralPath $privateDirectory) { Remove-Item -LiteralPath $privateDirectory -Recurse -Force -ErrorAction SilentlyContinue }
}
