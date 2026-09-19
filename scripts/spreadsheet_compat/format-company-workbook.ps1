param([Parameter(Mandatory=$true)][string]$WorkbookPath, [Parameter(Mandatory=$true)][string]$SnapshotPath, [Parameter(Mandatory=$true)][string]$ProofPath)
$ErrorActionPreference = 'Stop'
$targetWorkbook = (Resolve-Path -LiteralPath $WorkbookPath).Path
$snapshot = Get-Content -LiteralPath $SnapshotPath -Raw | ConvertFrom-Json
$excel = New-Object -ComObject Excel.Application
$excel.Visible = $false
$excel.DisplayAlerts = $false
$book = $null
try {
    $book = $excel.Workbooks.Open($targetWorkbook)
    foreach ($sheet in $book.Worksheets) {
        $sheet.UsedRange.Font.Name = 'Aptos'
        $sheet.UsedRange.Font.Size = 10
        $sheet.Columns.Item('A').ColumnWidth = 59
        $sheet.Range('B:L').ColumnWidth = 17
        $sheet.Rows.Item(1).RowHeight = 30
        $sheet.Rows.Item(2).RowHeight = 32
        $sheet.Range('A1:L2').WrapText = $true
        $sheet.PageSetup.Orientation = 2
        $sheet.PageSetup.Zoom = $false
        $sheet.PageSetup.FitToPagesWide = 1
        $sheet.PageSetup.FitToPagesTall = $false
        $sheet.PageSetup.PrintTitleRows = '$1:$3'
        $sheet.Activate()
        $excel.ActiveWindow.SplitRow = 3
        $excel.ActiveWindow.SplitColumn = 1
        $excel.ActiveWindow.FreezePanes = $true
    }
    foreach ($name in @('Review','Inputs','SavedInputs','Evidence')) {
        $sheet = $book.Worksheets.Item($name)
        $sheet.UsedRange.WrapText = $true
        if ($name -eq 'Review') { $sheet.Columns.Item('B').ColumnWidth = 104 }
        if ($name -in @('Inputs','SavedInputs')) { $sheet.Columns.Item('C').ColumnWidth = 95 }
        if ($name -eq 'Evidence') {
            $sheet.Columns.Item('B').ColumnWidth = 58
            $sheet.Columns.Item('D').ColumnWidth = 65
            $sheet.Columns.Item('A').ColumnWidth = 10
        }
        $sheet.UsedRange.Rows.AutoFit() | Out-Null
        $sheet.UsedRange.VerticalAlignment = -4160
        foreach ($wrappedRow in $sheet.UsedRange.Rows) {
            $wrappedRow.RowHeight = [Math]::Min(409.5, [double]$wrappedRow.RowHeight + 6)
        }
    }
    $review = $book.Worksheets.Item('Review')
    $review.Range('B4').NumberFormat = '$0.00'
    $review.Range('B5').NumberFormat = '0.00%'
    $review.Range('D3:D8').Hyperlinks.Delete()
    $row = 3
    foreach ($name in @('Inputs','History','Evidence','Schedules','DCF','Sensitivity')) {
        $review.Hyperlinks.Add($review.Cells.Item($row,4), '', "'$name'!A1", "Open $name", "Open $name") | Out-Null
        $row++
    }
    $book.Worksheets.Item('DCF').Range('B4:B7').NumberFormat = '0.00%'
    $book.Worksheets.Item('DCF').Range('B19').NumberFormat = '$0.00'
    $excel.CalculateFullRebuild()
    $dcf = $book.Worksheets.Item('DCF')
    $value = [double]$dcf.Range('B19').Value2
    if ([Math]::Abs($value - [double]$snapshot.per_share_value) -gt 0.000001) { throw 'Native Excel valuation differs from Mog' }
    $schedules = $book.Worksheets.Item('Schedules')
    $maximum = 0.0
    $valuesChecked = 0
    for ($r = 4; $r -le 55; $r++) {
        $label = [string]$schedules.Cells.Item($r,1).Value2
        $expected = $snapshot.schedules.PSObject.Properties[$label].Value
        for ($c = 2; $c -le 12; $c++) {
            $difference = [Math]::Abs([double]$schedules.Cells.Item($r,$c).Value2 - [double]$expected[$c-2])
            $maximum = [Math]::Max($maximum,$difference)
            $valuesChecked++
        }
    }
    if ($maximum -gt 0.000001) { throw 'Native Excel schedule values differ from Mog' }
    $inputs = $book.Worksheets.Item('Inputs')
    $betaCell = $inputs.Cells.Item([int]$snapshot.input_rows.beta,2)
    $priorBeta = [double]$betaCell.Value2
    $betaCell.Value2 = $priorBeta + 0.1
    $excel.CalculateFullRebuild()
    if ($dcf.Range('B20').Value2 -ne 'EDITED_UNREVIEWED' -or [Math]::Abs([double]$dcf.Range('B19').Value2-$value) -lt 0.000001) { throw 'Native Excel edit invalidation failed' }
    $betaCell.Value2 = $priorBeta
    $excel.CalculateFullRebuild()
    if ([Math]::Abs([double]$dcf.Range('B19').Value2-$value) -gt 0.000001) { throw 'Native restoration changed value' }
    $review.Activate()
    $excel.ActiveWindow.ScrollRow = 1
    $excel.ActiveWindow.ScrollColumn = 1
    $book.Save()
    @{ status='PASS'; excel_version=$excel.Version; values_checked=$valuesChecked; maximum_difference=$maximum; per_share_value=$value; native_beta_edit='PASS'; hyperlinks=$review.Hyperlinks.Count } | ConvertTo-Json | Set-Content -LiteralPath $ProofPath -Encoding utf8
} finally {
    if ($null -ne $book) { $book.Close($false) }
    $excel.Quit()
    [System.Runtime.InteropServices.Marshal]::ReleaseComObject($excel) | Out-Null
}
