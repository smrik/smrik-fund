param(
    [Parameter(Mandatory = $true)][string]$WorkbookPath,
    [Parameter(Mandatory = $true)][string]$ResultsPath
)

$ErrorActionPreference = 'Stop'
$tolerance = 1e-8
$fullWorkbook = [System.IO.Path]::GetFullPath($WorkbookPath)
$fullResults = [System.IO.Path]::GetFullPath($ResultsPath)
$proofPath = Join-Path ([System.IO.Path]::GetDirectoryName($fullWorkbook)) 'equity-verification.json'
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
function Assert-Array($sheet, [int]$row, [double[]]$expected, [string]$label) {
    for ($index = 0; $index -lt $expected.Count; $index++) {
        $column = [char]([int][char]'B' + $index)
        Assert-Close (Value $sheet "${column}${row}") $expected[$index] "${label}[${index}]"
    }
}
function Recalculate($excel) {
    $excel.CalculateFullRebuild()
    Start-Sleep -Milliseconds 250
}

if ([System.IO.Path]::GetExtension($fullWorkbook) -ne '.xlsx') { throw "P8C native proof requires an .xlsx workbook: $fullWorkbook" }
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

    $columns = @('B','C','D','E','F','G','H','I','J','K','L')

    $inputs = $book.Worksheets.Item('Inputs')
    $income = $book.Worksheets.Item('Income')
    $cash = $book.Worksheets.Item('CashFlow')
    $schedules = $book.Worksheets.Item('Schedules')
    $equity = $book.Worksheets.Item('Equity')
    $dcf = $book.Worksheets.Item('DCF')
    $checks = $book.Worksheets.Item('Checks')
    $review = $book.Worksheets.Item('Review')

    foreach ($column in @('B','C','D','E','F','G','H','I','J','K','L')) {
        if ((Value $checks "${column}20") -ne 'PASS') { throw "Excel mechanical check failed at ${column}20" }
    }
    if ((Value $inputs 'B185') -ne 'PASS') { throw 'Excel P8C input gate failed' }
    if ((Value $checks 'B22') -ne 'PASS') { throw 'Excel all-period gate failed' }
    Assert-Close (Value $income 'B11') $proof.snapshot.stub.ebit 'Excel/Mog book EBIT'
    Assert-Close (Value $income 'B15') $proof.snapshot.stub.netIncome 'Excel/Mog net income'
    Assert-Close (Value $cash 'B12') $proof.snapshot.stub.cfo 'Excel/Mog CFO'
    Assert-Close (Value $cash 'B18') $proof.snapshot.stub.closingCash 'Excel/Mog closing cash'
    Assert-Close (Value $equity 'B32') $proof.snapshot.stub.economicUfcf 'Excel/Mog equity UFCF'
    Assert-Close (Value $dcf 'B7') $proof.snapshot.stub.economicUfcf 'Excel/Mog DCF UFCF'
    Assert-Formula $equity 'B25' 'Equity!B25' | Out-Null
    Assert-Formula $equity 'B32' 'Equity!B32' | Out-Null
    Assert-Formula $dcf 'B7' 'DCF!B7' | Out-Null
    $claimFormula = Assert-Formula $dcf 'B26' 'DCF!B26 existing-award claim' 
    if ($claimFormula -ne '=Equity!B40') { throw "DCF!B26 must link Equity!B40, got $claimFormula" }
    $postClaimFormula = Assert-Formula $dcf 'B27' 'DCF!B27 post-claim equity'
    if (([regex]::Matches($postClaimFormula, 'B26', [System.Text.RegularExpressions.RegexOptions]::IgnoreCase)).Count -ne 1 -or -not $postClaimFormula.Contains('B22')) { throw "DCF!B27 must deduct the claim exactly once, got $postClaimFormula" }
    $pointShareFormula = Assert-Formula $dcf 'B28' 'DCF!B28 measurement-date point shares'
    if ($pointShareFormula -ne '=Inputs!$B$227') { throw "DCF!B28 must use Inputs!B227, got $pointShareFormula" }
    $perShareFormula = Assert-Formula $dcf 'B29' 'DCF!B29 partial value per share'
    if (([regex]::Matches($perShareFormula, 'B27', [System.Text.RegularExpressions.RegexOptions]::IgnoreCase)).Count -ne 1 -or ([regex]::Matches($perShareFormula, 'B28', [System.Text.RegularExpressions.RegexOptions]::IgnoreCase)).Count -ne 1) { throw "DCF!B29 must tie B27/B28, got $perShareFormula" }
    foreach ($address in @('B30','B31','B32')) { if ((Value $dcf $address) -ne 'PASS') { throw "P8C DCF claim/per-share check failed at $address" } }
    Assert-Close (Value $dcf 'B26') 30353.94 'Existing-award claim'
    Assert-Close (Value $dcf 'B27') (([double](Value $dcf 'B22')) - 30353.94) 'Partial equity after existing-award claim'
    Assert-Close (Value $dcf 'B28') 7429 'Measurement-date point-share denominator'
    Assert-Close (Value $dcf 'B29') (([double](Value $dcf 'B27')) / 7429) 'Partial value per point share'
    Assert-Formula $inputs 'B187' 'Inputs!B187 linked output' | Out-Null
    Assert-Formula $inputs 'B224' 'Inputs!B224 live service-day driver' | Out-Null
    Assert-Formula $inputs 'B225' 'Inputs!B225 live service-day denominator' | Out-Null

    $baseServiceDays = @($columns | ForEach-Object { [double](Value $inputs "${_}224") })
    $baseTotalServiceDays = [double](Value $inputs 'B225')
    $baseExistingServiceCost = @($columns | ForEach-Object { [double](Value $inputs "${_}188") })
    $baseExistingUnits = @($columns | ForEach-Object { [double](Value $inputs "${_}190") })
    $baseDilutedIncrement = @($columns | ForEach-Object { [double](Value $inputs "${_}207") })
    if ([math]::Abs((($baseServiceDays | Measure-Object -Sum).Sum) - $baseTotalServiceDays) -gt $tolerance) { throw 'Base service calendar does not fully run off' }
    if ([math]::Abs((($baseExistingServiceCost | Measure-Object -Sum).Sum) - [double](Value $inputs 'B174')) -gt $tolerance) { throw 'Base existing service cost does not fully run off' }
    if ([math]::Abs((($baseExistingUnits | Measure-Object -Sum).Sum) - [double](Value $inputs 'B173')) -gt $tolerance) { throw 'Base existing units do not fully run off' }

    $base = [ordered]@{
        sbcRatio = [double](Value $inputs 'B172')
        settlementPrice = [double](Value $inputs 'B177')
        withholdingRate = [double](Value $inputs 'B178')
        repurchaseRatio = [double](Value $inputs 'B180')
        dividendPerShare = [double](Value $inputs 'B182')
        ebit = [double](Value $income 'B11')
        netIncome = [double](Value $income 'B15')
        cfo = [double](Value $cash 'B12')
        closingCash = [double](Value $cash 'B18')
        bookSbc = [double](Value $equity 'B6')
        newUnits = [double](Value $equity 'B10')
        withheldUnits = [double](Value $equity 'B11')
        withholdingCash = [double](Value $equity 'B19')
        programCash = [double](Value $equity 'B16')
        dividendDeclaration = [double](Value $equity 'B20')
        dividendCash = [double](Value $equity 'B23')
        closingShares = [double](Value $equity 'B25')
        weightedShares = [double](Value $equity 'B26')
        basicEps = [double](Value $equity 'B28')
        dilutedIncrement = [double](Value $equity 'B27')
        ufcf = [double](Value $equity 'B32')
        apic = [double](Value $equity 'B34')
        retainedEarnings = [double](Value $equity 'B35')
        equityBeforeClaim = [double](Value $dcf 'B22')
        existingAwardClaim = [double](Value $dcf 'B26')
        partialEquity = [double](Value $dcf 'B27')
        pointShareDenominator = [double](Value $dcf 'B28')
        partialPerShare = [double](Value $dcf 'B29')
        enterpriseValue = [double](Value $dcf 'B18')
    }
    $checksRun = [System.Collections.Generic.List[string]]::new()
    $checksRun.Add('Mog fingerprint and baseline values match')
    $checksRun.Add('Checks B20:L20 and P8C gate PASS')

    $inputs.Range('B172').Value2 = $base.sbcRatio * 1.1
    Recalculate $excel
    Assert-Changed (Value $income 'B11') $base.ebit 'SBC-ratio EBIT'
    Assert-Changed (Value $income 'B15') $base.netIncome 'SBC-ratio net income'
    Assert-Changed (Value $cash 'B12') $base.cfo 'SBC-ratio CFO'
    Assert-Changed (Value $equity 'B32') $base.ufcf 'SBC-ratio UFCF'
    Assert-Changed (Value $equity 'B34') $base.apic 'SBC-ratio APIC'
    Assert-Changed (Value $equity 'B28') $base.basicEps 'SBC-ratio EPS'
    if ((Value $review 'B3') -ne 'EDITED_UNREVIEWED') { throw 'SBC-ratio edit did not invalidate review binding' }
    $checksRun.Add('SBC-ratio edit changed EBIT/NI/CFO/UFCF/APIC/EPS and invalidated review')
    $inputs.Range('B172').Value2 = $base.sbcRatio
    Recalculate $excel
    Assert-Close (Value $income 'B11') $base.ebit 'SBC-ratio EBIT recovery'
    if ((Value $inputs 'B185') -ne 'PASS') { throw 'SBC-ratio recovery did not restore P8C gate' }

    $inputs.Range('B173').Value2 = 83
    Recalculate $excel
    Assert-Close (Value $dcf 'B26') ($base.existingAwardClaim + 370.17) 'One-more-award claim movement'
    Assert-Close (Value $dcf 'B27') ($base.partialEquity - 370.17) 'One-more-award partial equity movement'
    Assert-Close (Value $dcf 'B28') $base.pointShareDenominator 'One-more-award denominator invariant'
    Assert-Close (Value $dcf 'B29') ($base.partialPerShare - 370.17 / 7429) 'One-more-award partial per-share movement'
    Assert-Close (Value $dcf 'B18') $base.enterpriseValue 'One-more-award EV invariant'
    Assert-Close (Value $income 'B11') $base.ebit 'One-more-award EBIT invariant'
    Assert-Close (Value $income 'B15') $base.netIncome 'One-more-award net income invariant'
    Assert-Close (Value $cash 'B12') $base.cfo 'One-more-award CFO invariant'
    Assert-Close (Value $equity 'B32') $base.ufcf 'One-more-award UFCF invariant'
    if ((Value $review 'B3') -ne 'EDITED_UNREVIEWED') { throw 'One-more-award edit did not invalidate review binding' }
    $checksRun.Add('One additional existing unit changed only the claim/equity/per-share diagnostic by the expected amount')
    $inputs.Range('B173').Value2 = 82
    Recalculate $excel

    $dcf.Range('B27').Formula = '=B22'
    Recalculate $excel
    if ((Value $dcf 'B30') -ne 'FAIL') { throw 'Omitted existing-award deduction did not fail the DCF claim check' }
    $checksRun.Add('Omitted existing-award deduction failed the connected claim check')
    $dcf.Range('B27').Formula = $postClaimFormula
    Recalculate $excel
    $dcf.Range('B27').Formula = '=B22-B26-B26'
    Recalculate $excel
    if ((Value $dcf 'B30') -ne 'FAIL') { throw 'Duplicated existing-award deduction did not fail the DCF claim check' }
    $checksRun.Add('Duplicated existing-award deduction failed the connected claim check')
    $dcf.Range('B27').Formula = $postClaimFormula
    Recalculate $excel
    $dcf.Range('B28').Formula = '=Inputs!$B$227+Inputs!$B$173'
    Recalculate $excel
    if ((Value $dcf 'B31') -ne 'FAIL') { throw 'Double-counted point-share denominator did not fail the denominator check' }
    $checksRun.Add('Double-counted point-share denominator failed the denominator check')
    $dcf.Range('B28').Formula = $pointShareFormula
    Recalculate $excel

    $inputs.Range('B175').Value2 = 2
    Recalculate $excel
    if ((Value $inputs 'B185') -ne 'PASS') { throw 'Two-year service duration failed P8C gate' }
    Assert-Array $inputs 224 @(91,365,275,0,0,0,0,0,0,0,0) 'Two-year service days'
    Assert-Close (Value $inputs 'B225') 731 'Two-year service denominator'
    $twoCost = @($columns | ForEach-Object { [double](Value $inputs "${_}188") })
    $twoUnits = @($columns | ForEach-Object { [double](Value $inputs "${_}190") })
    if ([math]::Abs((($twoCost | Measure-Object -Sum).Sum) - [double](Value $inputs 'B174')) -gt $tolerance) { throw 'Two-year service cost does not fully run off' }
    if ([math]::Abs((($twoUnits | Measure-Object -Sum).Sum) - [double](Value $inputs 'B173')) -gt $tolerance) { throw 'Two-year existing units do not fully run off' }
    Assert-Changed (Value $inputs 'D188') $baseExistingServiceCost[2] 'Two-year FY2028 service cost'
    for ($index = 3; $index -lt $columns.Count; $index++) { Assert-Close (Value $inputs "$($columns[$index])188") 0 "Two-year trailing service cost[$index]"; Assert-Close (Value $inputs "$($columns[$index])190") 0 "Two-year trailing units[$index]"; Assert-Close (Value $inputs "$($columns[$index])207") 0 "Two-year trailing diluted increment[$index]" }
    $checksRun.Add('Years 3 to 2 changed live calendar, service cost and expired all awards without a diluted tail')

    $inputs.Range('B175').Value2 = 4
    Recalculate $excel
    if ((Value $inputs 'B185') -ne 'PASS') { throw 'Four-year service duration failed P8C gate' }
    Assert-Array $inputs 224 @(91,365,366,365,274,0,0,0,0,0,0) 'Four-year service days'
    Assert-Close (Value $inputs 'B225') 1461 'Four-year service denominator'
    $fourCost = @($columns | ForEach-Object { [double](Value $inputs "${_}188") })
    $fourUnits = @($columns | ForEach-Object { [double](Value $inputs "${_}190") })
    if ([math]::Abs((($fourCost | Measure-Object -Sum).Sum) - [double](Value $inputs 'B174')) -gt $tolerance) { throw 'Four-year service cost does not fully run off' }
    if ([math]::Abs((($fourUnits | Measure-Object -Sum).Sum) - [double](Value $inputs 'B173')) -gt $tolerance) { throw 'Four-year existing units do not fully run off' }
    Assert-Changed (Value $inputs 'E188') $baseExistingServiceCost[3] 'Four-year FY2029 service cost'
    $checksRun.Add('Years 2 to 4 changed live calendar and service denominator with full cost/unit expiry')

    $inputs.Range('B175').Value2 = 3
    Recalculate $excel
    if ((Value $inputs 'B185') -ne 'PASS') { throw 'Service duration restoration failed P8C gate' }
    Assert-Array $inputs 224 @(91,365,366,274,0,0,0,0,0,0,0) 'Restored three-year service days'
    Assert-Close (Value $inputs 'B225') $baseTotalServiceDays 'Restored service denominator'
    for ($index = 0; $index -lt $columns.Count; $index++) { Assert-Close (Value $inputs "$($columns[$index])188") $baseExistingServiceCost[$index] "Restored service cost[$index]"; Assert-Close (Value $inputs "$($columns[$index])190") $baseExistingUnits[$index] "Restored service units[$index]" }
    $fy27Units = [double](Value $equity 'C17')
    $fy27RollingBasis = [double](Value $equity 'C18')
    $fy27ExpectedBasis = [double](Value $equity 'B34') / [double](Value $equity 'C24') * $fy27Units
    $measurementBasis = [double](Value $inputs 'B228') / [double](Value $inputs 'B227') * $fy27Units
    Assert-Close $fy27RollingBasis $fy27ExpectedBasis 'FY2027 opening APIC retirement basis'
    Assert-Changed $fy27RollingBasis $measurementBasis 'FY2027 rolling versus measurement APIC basis'
    $checksRun.Add('Restored three-year duration and verified FY2027 opening APIC basis rolls from FY2026 closing values')

    $inputs.Range('B177').Value2 = $base.settlementPrice * 1.1
    Recalculate $excel
    Assert-Changed (Value $equity 'B10') $base.newUnits 'settlement-price gross units'
    Assert-Changed (Value $equity 'B26') $base.weightedShares 'settlement-price weighted shares'
    $checksRun.Add('Settlement-price edit changed delivered-unit and EPS denominator outputs')
    $inputs.Range('B177').Value2 = $base.settlementPrice
    Recalculate $excel

    $inputs.Range('B177').Value2 = 1
    Recalculate $excel
    if ((Value $inputs 'B185') -ne 'FAIL') { throw 'Below-basis settlement price did not fail P8C gate' }
    $checksRun.Add('Below-basis settlement price blocked the affected retirement periods')
    $inputs.Range('B177').Value2 = $base.settlementPrice
    Recalculate $excel

    $inputs.Range('B221').Value2 = 1
    $inputs.Range('B222').Value2 = 1
    $inputs.Range('B223').Value2 = 1
    Recalculate $excel
    Assert-Close (Value $equity 'B25') $base.closingShares 'timing point shares invariant'
    Assert-Changed (Value $equity 'B26') $base.weightedShares 'timing weighted shares'
    Assert-Changed (Value $equity 'B28') $base.basicEps 'timing EPS'
    $checksRun.Add('Distinct delivery/issuance/repurchase timing changed weighted shares and EPS while point shares stayed fixed')
    $inputs.Range('B221').Value2 = 0.5
    $inputs.Range('B222').Value2 = 0.5
    $inputs.Range('B223').Value2 = 0.5
    Recalculate $excel

    $inputs.Range('B178').Value2 = 0.5
    Recalculate $excel
    Assert-Changed (Value $equity 'B11') $base.withheldUnits 'withholding units'
    Assert-Changed (Value $equity 'B19') $base.withholdingCash 'withholding cash'
    Assert-Changed (Value $equity 'B34') $base.apic 'withholding APIC'
    Assert-Changed (Value $cash 'B18') $base.closingCash 'withholding closing cash'
    $checksRun.Add('Withholding edit changed withheld units/APIC/cash')
    $inputs.Range('B178').Value2 = $base.withholdingRate
    Recalculate $excel

    $inputs.Range('B180').Value2 = $base.repurchaseRatio * 0.5
    $inputs.Range('B182').Value2 = $base.dividendPerShare * 1.1
    Recalculate $excel
    Assert-Changed (Value $equity 'B16') $base.programCash 'program cash'
    Assert-Changed (Value $equity 'B20') $base.dividendDeclaration 'dividend declaration'
    Assert-Changed (Value $equity 'B35') $base.retainedEarnings 'capital-return retained earnings'
    Assert-Changed (Value $cash 'B18') $base.closingCash 'capital-return closing cash'
    $checksRun.Add('Program/dividend edits changed cash, retained earnings and closing cash')
    $inputs.Range('B180').Value2 = $base.repurchaseRatio
    $inputs.Range('B182').Value2 = $base.dividendPerShare
    Recalculate $excel

    $baseScheduleFormula = [string]$schedules.Range('B11').Formula
    $schedules.Range('B11').Formula = '=B10*2'
    Recalculate $excel
    Assert-Close (Value $equity 'B27') 0 'loss antidilutive increment'
    $checksRun.Add('Loss period excluded diluted increment')
    $schedules.Range('B11').Formula = $baseScheduleFormula
    Recalculate $excel

    $inputs.Range('B177').ClearContents()
    Recalculate $excel
    if ((Value $inputs 'B185') -ne 'FAIL') { throw 'Missing settlement price did not fail P8C gate' }
    if ((Value $dcf 'B18') -ne 'BLOCKED') { throw 'Missing settlement price did not block DCF' }
    $checksRun.Add('Missing price blocked the gate and DCF')
    $inputs.Range('B177').Value2 = $base.settlementPrice
    Recalculate $excel

    $inputs.Range('B179').Value2 = 0
    $inputs.Range('B180').Value2 = 0
    Recalculate $excel
    if ((Value $inputs 'B185') -ne 'PASS') { throw 'Supported zero issuance/repurchase failed P8C gate' }
    Assert-Close (Value $equity 'B13') 0 'zero cash issuance'
    Assert-Close (Value $equity 'B16') 0 'zero program repurchase'
    $checksRun.Add('Supported zero issuance and repurchase remained valid')

    $book.Close($false)
    $book = $null
    $excel.Quit()
    $excel = $null
    $publishedAfter = Sha256 $fullWorkbook
    if ($publishedBefore -ne $publishedAfter) { throw 'Published workbook bytes changed during private Excel proof' }
    $result = [ordered]@{
        status = 'PASS'
        mode = 'native invisible Excel P8C recalculation with live SBC, price, timing, withholding, program, dividend, loss, missing and zero guards'
        publishedSha256Before = $publishedBefore
        publishedSha256After = $publishedAfter
        workbookPath = $fullWorkbook
        checks = $checksRun
    }
    $result | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $fullResults -Encoding utf8
    Write-Output ($result | ConvertTo-Json -Depth 8)
} finally {
    if ($book -ne $null) { $book.Close($false) }
    if ($excel -ne $null) { $excel.Quit() }
    Remove-Item -LiteralPath $working -Force -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath $privateDirectory -Recurse -Force -ErrorAction SilentlyContinue
}
