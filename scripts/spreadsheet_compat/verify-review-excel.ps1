param(
    [Parameter(Mandatory = $true)][string]$VersionDirectory,
    [Parameter(Mandatory = $true)][string]$ResultsPath,
    [Parameter(Mandatory = $true)][string]$EditedCopyPath
)

$ErrorActionPreference = 'Stop'
$tolerance = 0.00001
$versionRoot = [System.IO.Path]::GetFullPath($VersionDirectory)
$version = Get-Content -LiteralPath (Join-Path $versionRoot 'version.json') -Raw | ConvertFrom-Json
$proof = Get-Content -LiteralPath $version.snapshot_path -Raw | ConvertFrom-Json
$model = Get-Content -LiteralPath $version.model_path -Raw | ConvertFrom-Json
$working = [System.IO.Path]::GetFullPath($EditedCopyPath)
$resultFile = [System.IO.Path]::GetFullPath($ResultsPath)
if (Test-Path -LiteralPath $working) { throw 'Edited copy already exists; it will not be overwritten' }
if (Test-Path -LiteralPath $resultFile) { throw 'Native result already exists; choose a new path' }

function Sha256([string]$path) { return (Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash.ToLowerInvariant() }
function Value($sheet, [string]$address) { return $sheet.Range($address).Value2 }
function Assert-Close($actual, $expected, [string]$label) {
    if ($null -eq $actual -or $actual -is [string] -or [math]::Abs([double]$actual - [double]$expected) -gt $tolerance) { throw "$label expected $expected, got $actual" }
}
function Assert-Text($actual, [string]$expected, [string]$label) {
    if ([string]$actual -ne $expected) { throw "$label expected $expected, got $actual" }
}
function Recalculate($excel) { $excel.CalculateFullRebuild(); Start-Sleep -Milliseconds 200 }
function Assert-Formula($sheet, [string]$address) {
    $formula = [string]$sheet.Range($address).Formula
    if (-not $formula.StartsWith('=')) { throw "Lost formula: $($sheet.Name)!$address" }
    return $formula
}

$publishedBefore = Sha256 $version.workbook_path
if ($publishedBefore -ne $version.workbook_sha256 -or $publishedBefore -ne $proof.workbookSha256) { throw 'Version/workbook/snapshot binding mismatch' }
New-Item -ItemType Directory -Force -Path ([System.IO.Path]::GetDirectoryName($working)) | Out-Null
New-Item -ItemType Directory -Force -Path ([System.IO.Path]::GetDirectoryName($resultFile)) | Out-Null
[System.IO.File]::Copy($version.workbook_path, $working, $false)
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
    $review = $book.Worksheets.Item('Review')
    $valuation = $book.Worksheets.Item('Valuation')
    $inputs = $book.Worksheets.Item('Inputs')
    $saved = $book.Worksheets.Item('SavedInputs')
    $cf = $book.Worksheets.Item('CashFlow')
    $bs = $book.Worksheets.Item('BalanceSheet')
    $sens = $book.Worksheets.Item('P9Sensitivity')
    $groups = [System.Collections.Generic.List[object]]::new()

    $cellCount = 0
    foreach ($statement in $proof.snapshot.statements.psobject.Properties) {
        $sheetName = @{ income = 'Income'; cashFlow = 'CashFlow'; balanceSheet = 'BalanceSheet' }[$statement.Name]
        $sheet = $book.Worksheets.Item($sheetName)
        foreach ($row in $statement.Value) {
            for ($index = 0; $index -lt 11; $index++) {
                $address = ([char](66 + $index)).ToString() + $row.row
                Assert-Close (Value $sheet $address) $row.values[$index] "$sheetName!$address"
                $cellCount++
            }
        }
    }
    $groups.Add(@{ name = 'all-550-native-statement-values-match-Mog'; status = 'PASS'; cells = $cellCount })
    Assert-Text (Value $review 'C14') 'PASS' 'Mechanical state'
    Assert-Text (Value $review 'C15') 'COMPLETE' 'Coverage state'
    Assert-Text (Value $review 'C16') $model.review_metadata.states.analytical 'Analytical state'
    Assert-Text (Value $valuation 'B3') $model.review_metadata.states.analytical 'Valuation state'
    Assert-Text (Value $review 'C18') 'false' 'Human approval'
    Assert-Close (Value $review 'B23') $version.per_share_value 'Front-sheet per share'
    Assert-Close (Value $review 'B21') $proof.snapshot.p9.enterpriseValue 'Front-sheet enterprise value'
    $groups.Add(@{ name = 'separate-live-states-and-front-values'; status = 'PASS' })

    $links = 0
    foreach ($row in 37..49) {
        $formula = Assert-Formula $review "B$row"
        if ($formula -notmatch 'HYPERLINK') { throw "Missing navigation link B$row" }
        $links++
    }
    foreach ($index in 0..11) {
        $row = 52 + $index
        $area = $model.review_metadata.areas[$index]
        Assert-Text (Value $review "A$row") $area.area "Area $row"
        foreach ($column in @('F', 'G')) {
            $formula = Assert-Formula $review "$column$row"
            if ($formula -notmatch "#'([^']+)'!([A-Z]+[0-9]+)") { throw "Missing area link $column$row" }
            $targetSheet = $book.Worksheets.Item($Matches[1])
            $target = [string](Value $targetSheet $Matches[2])
            if ($column -eq 'F' -and $target -ne $area.area) { throw 'Decision link resolves to wrong area' }
            if ($column -eq 'G' -and $target -ne $area.source_refs[0]) { throw 'Evidence link resolves to wrong source' }
            $links++
        }
    }
    $groups.Add(@{ name = 'native-navigation-and-all-material-decisions'; status = 'PASS'; links = $links })
    foreach ($item in $model.review_metadata.material_inputs) {
        $parts = $item.address.Split('!')
        $sheet = $book.Worksheets.Item($parts[0])
        $comment = $sheet.Range($parts[1]).Comment
        if ($null -eq $comment) { throw "Missing native input note: $($item.address)" }
        $note = [string]$comment.Text()
        if (-not $note.Contains('Exported-base rationale') -or -not $note.Contains($item.source_refs[0])) { throw "Incomplete native note: $($item.address)" }
    }
    $groups.Add(@{ name = 'native-source-and-assumption-notes'; status = 'PASS'; notes = $model.review_metadata.material_inputs.Count })

    $betaRow = 0
    foreach ($row in 4..$saved.UsedRange.Rows.Count) { if ((Value $saved "A$row") -eq 'Valuation!B14') { $betaRow = $row; break } }
    if ($betaRow -eq 0) { throw 'Missing exported/current beta row' }
    $baseBeta = [double](Value $valuation 'B14')
    $valuation.Range('B14').Value2 = 1.15
    Recalculate $excel
    Assert-Close (Value $valuation 'B122') 210.06222140921045 'Native beta1.15 value'
    Assert-Text (Value $review 'C15') 'STALE_AFTER_EDIT' 'Edited coverage'
    Assert-Text (Value $review 'C16') 'EDITED_UNREVIEWED' 'Edited analysis'
    Assert-Text (Value $valuation 'B3') 'EDITED_UNREVIEWED' 'Edited valuation analysis'
    Assert-Close (Value $saved "B$betaRow") $baseBeta 'Exported beta preserved'
    Assert-Close (Value $saved "D$betaRow") 1.15 'Current beta'
    Assert-Close (Value $saved "C$betaRow") 1 'Beta changed flag'
    $betaValue = [double](Value $valuation 'B122')
    $betaWacc = [double](Value $valuation 'B39')
    $groups.Add(@{ name = 'consequential-local-beta-edit'; status = 'PASS'; beta = 1.15; perShareValue = $betaValue; wacc = $betaWacc })
    $valuation.Range('B14').Value2 = $baseBeta
    Recalculate $excel

    $baseCapex = [double](Value $inputs 'B32')
    $baseCash = [double](Value $cf 'L18')
    $basePpe = [double](Value $bs 'L11')
    $inputs.Range('B32').Value2 = 0.25
    Recalculate $excel
    Assert-Text (Value $review 'C14') 'PASS' 'Changed capex mechanics'
    Assert-Text (Value $review 'C16') 'EDITED_UNREVIEWED' 'Changed capex review'
    if ([math]::Abs([double](Value $cf 'L18') - $baseCash) -le $tolerance) { throw 'Capex did not propagate to cash' }
    if ([math]::Abs([double](Value $bs 'L11') - $basePpe) -le $tolerance) { throw 'Capex did not propagate to balance-sheet PP&E' }
    $groups.Add(@{ name = 'local-operating-input-propagates-through-statements'; status = 'PASS' })
    $inputs.Range('B32').Value2 = $baseCapex
    Recalculate $excel
    Assert-Close (Value $valuation 'B122') $version.per_share_value 'Restored base'
    $spread = [double](Value $valuation 'B15')
    Assert-Close (Value $sens 'C14') 0 'Credit-spread floor'
    $valuation.Range('B15').Value2 = -0.001
    Recalculate $excel
    Assert-Text (Value $valuation 'B122') 'BLOCKED' 'Negative-spread block'
    $valuation.Range('B15').Value2 = $spread
    Recalculate $excel
    Assert-Close (Value $valuation 'B122') $version.per_share_value 'Spread recovery'
    $groups.Add(@{ name = 'credit-spread-floor-invalid-input-and-recovery'; status = 'PASS' })

    # Keep the consequential local edit as a distinct, explicitly unreviewed copy.
    $valuation.Range('B14').Value2 = 1.15
    Recalculate $excel
    $book.Save()
    $book.Close($false)
    $book = $null
    if ((Sha256 $version.workbook_path) -ne $publishedBefore) { throw 'Published workbook changed during native proof' }
    $result = @{ status = 'PASS'; purpose = 'P11 native Excel review and P12 local-to-CLI revision comparison'; case = 'MSFT'; measurement_date = '2026-03-31'; information_cutoff = '2026-04-30'; units = 'USD millions except per-share'; excel_version = [string]$excel.Version; source_version = $version.version; published_sha256 = $publishedBefore; published_preserved = $true; edited_copy = $working; edited_copy_sha256 = (Sha256 $working); edited_state = 'EDITED_UNREVIEWED'; beta = 1.15; per_share_value = $betaValue; wacc = $betaWacc; human_approval = $false; groups = $groups.ToArray() }
    $result | ConvertTo-Json -Depth 12 | Set-Content -LiteralPath $resultFile -Encoding UTF8
    $result | ConvertTo-Json -Depth 12
}
finally {
    if ($null -ne $book) { $book.Close($false) }
    if ($null -ne $excel) { $excel.Quit(); [void][System.Runtime.InteropServices.Marshal]::FinalReleaseComObject($excel) }
    [GC]::Collect()
    [GC]::WaitForPendingFinalizers()
}
