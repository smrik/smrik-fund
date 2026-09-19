param(
    [Parameter(Mandatory = $true)][string]$VersionDirectory,
    [Parameter(Mandatory = $true)][string]$LocalEditProof,
    [Parameter(Mandatory = $true)][string]$ResultsPath
)
$ErrorActionPreference = 'Stop'
$version = Get-Content -LiteralPath (Join-Path $VersionDirectory 'version.json') -Raw | ConvertFrom-Json
$snapshot = (Get-Content -LiteralPath $version.snapshot_path -Raw | ConvertFrom-Json).snapshot
$edit = Get-Content -LiteralPath $LocalEditProof -Raw | ConvertFrom-Json
$resultPath = [System.IO.Path]::GetFullPath($ResultsPath)
if (Test-Path -LiteralPath $resultPath) { throw 'Comparison proof already exists; preserve it' }
function Hash([string]$path) { return (Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash.ToLowerInvariant() }
function Close-Enough($a, $b, [string]$label) {
    if ($null -eq $a -or $null -eq $b -or $a -is [string] -or $b -is [string] -or [math]::Abs([double]$a - [double]$b) -gt 0.00001) { throw "$label mismatch: $a vs $b" }
}
if ((Hash $version.workbook_path) -ne $version.workbook_sha256 -or (Hash $edit.edited_copy) -ne $edit.edited_copy_sha256) { throw 'Source workbook binding mismatch' }
$excel = $null
$authoritative = $null
$local = $null
try {
    $excel = New-Object -ComObject Excel.Application
    $excel.Visible = $false
    $excel.DisplayAlerts = $false
    $excel.EnableEvents = $false
    $excel.AutomationSecurity = 3
    $authoritative = $excel.Workbooks.Open($version.workbook_path, 0, $true)
    $local = $excel.Workbooks.Open($edit.edited_copy, 0, $true)
    $excel.Calculation = -4105
    $excel.Iteration = $false
    $excel.CalculateFullRebuild()
    $aVal = $authoritative.Worksheets.Item('Valuation')
    $lVal = $local.Worksheets.Item('Valuation')
    if ([string]$authoritative.Worksheets.Item('Review').Range('C16').Value2 -ne 'RECHECK_ACCEPTED') { throw 'Authoritative revision review was not retained in native Excel' }
    if ([string]$local.Worksheets.Item('Review').Range('C16').Value2 -ne 'EDITED_UNREVIEWED') { throw 'Local edit falsely claims reviewed state' }
    foreach ($address in @('B14','B27','B39','B50','B76','B120','B121','B122')) {
        Close-Enough $aVal.Range($address).Value2 $lVal.Range($address).Value2 "Native revision $address"
    }
    Close-Enough $aVal.Range('B122').Value2 $version.per_share_value 'Native/Mog revised value'
    Close-Enough $aVal.Range('B122').Value2 $edit.per_share_value 'Native local edit/CLI revision value'
    $cells = 0
    foreach ($statement in $snapshot.statements.psobject.Properties) {
        $sheetName = @{income='Income';cashFlow='CashFlow';balanceSheet='BalanceSheet'}[$statement.Name]
        $aSheet = $authoritative.Worksheets.Item($sheetName)
        $lSheet = $local.Worksheets.Item($sheetName)
        foreach ($row in $statement.Value) {
            foreach ($index in 0..10) {
                $address = ([char](66 + $index)).ToString() + $row.row
                Close-Enough $aSheet.Range($address).Value2 $lSheet.Range($address).Value2 "$sheetName!$address local/CLI"
                Close-Enough $aSheet.Range($address).Value2 $row.values[$index] "$sheetName!$address native/Mog"
                $cells++
            }
        }
    }
    $note = [string]$aVal.Range('B14').Comment.Text()
    if (-not $note.Contains('Exported base: 1.15') -or -not $note.Contains('MKT-BETA')) { throw 'Revision beta note did not update' }
    $value = [double]$aVal.Range('B122').Value2
    $authoritative.Close($false); $authoritative = $null
    $local.Close($false); $local = $null
    if ((Hash $version.workbook_path) -ne $version.workbook_sha256 -or (Hash $edit.edited_copy) -ne $edit.edited_copy_sha256) { throw 'Native comparison changed a source workbook' }
    $result = @{status='PASS';purpose='P12 consequential Excel edit -> confirmed reviewed CLI revision comparison';authoritative_version=$version.version;authoritative_workbook=$version.workbook_path;local_edit=$edit.edited_copy;statement_cells_compared=$cells;valuation_cells_compared=8;beta=1.15;per_share_value=$value;authoritative_review='RECHECK_ACCEPTED';local_edit_review='EDITED_UNREVIEWED';updated_beta_note=$true;both_workbooks_preserved=$true;human_financial_approval=$false;excel_version=[string]$excel.Version}
    $result | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $resultPath -Encoding UTF8
    $result | ConvertTo-Json -Depth 6
}
finally {
    if ($null -ne $authoritative) { $authoritative.Close($false) }
    if ($null -ne $local) { $local.Close($false) }
    if ($null -ne $excel) { $excel.Quit(); [void][System.Runtime.InteropServices.Marshal]::FinalReleaseComObject($excel) }
    [GC]::Collect(); [GC]::WaitForPendingFinalizers()
}
