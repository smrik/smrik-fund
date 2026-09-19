param([Parameter(Mandatory=$true)][string]$WorkbookPath, [Parameter(Mandatory=$true)][string]$SnapshotPath, [Parameter(Mandatory=$true)][string]$ProofPath)
$ErrorActionPreference = 'Stop'
$targetWorkbook = (Resolve-Path -LiteralPath $WorkbookPath).Path
$snapshot = Get-Content -LiteralPath $SnapshotPath -Raw | ConvertFrom-Json
$excel = New-Object -ComObject Excel.Application
$excel.Visible = $false
$excel.DisplayAlerts = $false
$excel.AutomationSecurity = 3
$book = $null
try {
    $book = $excel.Workbooks.Open($targetWorkbook,0)
    foreach ($sheet in $book.Worksheets) {
        $sheet.UsedRange.Font.Name = 'Aptos'
        $sheet.UsedRange.Font.Size = 10
        $sheet.Columns.Item('A').ColumnWidth = 59
        $sheet.Range($sheet.Cells.Item(1,2), $sheet.Cells.Item(1,[Math]::Max(12,$sheet.UsedRange.Columns.Count))).EntireColumn.ColumnWidth = 17
        $sheet.Rows.Item(3).RowHeight = 42
        $sheet.Rows.Item(3).WrapText = $true
        $sheet.Rows.Item(1).RowHeight = 30
        $sheet.Rows.Item(2).RowHeight = 32
        $sheet.Range('A1:L2').WrapText = $true
        $lastColumn=[Math]::Max(2,$sheet.UsedRange.Columns.Count)
        foreach ($r in @(1,2)) {
            $heading=$sheet.Range($sheet.Cells.Item($r,1),$sheet.Cells.Item($r,$lastColumn))
            $heading.Merge() | Out-Null
            $heading.VerticalAlignment=-4108
        }
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
    foreach ($name in @('Income','BalanceSheet','CashFlow','History','DCF','Sensitivity')) {
        $review.Hyperlinks.Add($review.Cells.Item($row,4), '', "'$name'!A1", "Open $name", "Open $name") | Out-Null
        $row++
    }
    $book.Worksheets.Item('DCF').Range('B4:B7').NumberFormat = '0.00%'
    $book.Worksheets.Item('DCF').Range('B19').NumberFormat = '$0.00'
    $excel.CalculateFullRebuild()
    $dcf = $book.Worksheets.Item('DCF')
    $value = [double]$dcf.Range('B19').Value2
    if ([Math]::Abs($value - [double]$snapshot.per_share_value) -gt 0.000001) { throw 'Native Excel valuation differs from Mog' }
    $maximum = 0.0
    $valuesChecked = 0
    foreach ($metric in $snapshot.schedule_cells.PSObject.Properties) {
        $expected = $snapshot.schedules.PSObject.Properties[$metric.Name].Value
        for ($i=0; $i -lt $metric.Value.Count; $i++) {
            $binding=$metric.Value[$i]
            if ($null -ne $binding.constant) { $actual=[double]$binding.constant }
            else { $actual=[double]$book.Worksheets.Item($binding.sheet).Range($binding.cell).Value2 }
            $difference=[Math]::Abs($actual-[double]$expected[$i])
            $maximum=[Math]::Max($maximum,$difference)
            $valuesChecked++
        }
    }
    if ($maximum -gt 0.000001) { throw 'Native Excel statement values differ from formula engine' }
    $operatingChecked=0
    foreach ($item in $snapshot.operating_checks) {
        $actual=$book.Worksheets.Item($item.sheet).Range($item.cell).Value2
        if ($null -eq $actual -or [Math]::Abs([double]$actual-[double]$item.value) -gt 0.000001) { throw "Operating build mismatch: $($item.sheet)!$($item.cell)" }
        $operatingChecked++
    }
    $historyChecked=0
    foreach ($item in $snapshot.historical_checks) {
        $actual=$book.Worksheets.Item($item.sheet).Range($item.cell).Value2
        if ($null -eq $actual -or [Math]::Abs([double]$actual-[double]$item.value) -gt 0.000001) { throw "Historical source mismatch: $($item.sheet)!$($item.cell)" }
        $historyChecked++
    }
    foreach ($name in @('Income','BalanceSheet','CashFlow','Assets','WorkingCapital')) {
        $sheet=$book.Worksheets.Item($name)
        $last=$sheet.UsedRange.Columns.Count
        $historicalEnd=[int]$snapshot.presentation.history_columns+2
        $sheet.Range($sheet.Cells.Item(3,2),$sheet.Cells.Item(3,$historicalEnd)).Interior.Color=15132390
        $sheet.Range($sheet.Cells.Item(3,$historicalEnd+1),$sheet.Cells.Item(3,$last)).Interior.Color=15917529
        $sheet.PageSetup.PrintArea=$sheet.UsedRange.Address()
        $sheet.Range($sheet.Cells.Item(4,2),$sheet.Cells.Item($sheet.UsedRange.Rows.Count,$last)).Font.Color=0
        try {
            $formulaCells=$sheet.UsedRange.SpecialCells(-4123)
            foreach ($cell in $formulaCells.Cells) {
                if ([string]$cell.Formula -match '!') { $cell.Font.Color=32768 }
            }
        } catch { }
        $totals=switch ($name) {
            'Income' { @(8,14,26,32,38,47,51) }
            'BalanceSheet' { @(15,24,29,32) }
            'CashFlow' { @(14,20,25,30,33,35) }
            'Assets' { @(14,22) }
            'WorkingCapital' { @(23,25) }
        }
        foreach ($r in $totals) {
            $range=$sheet.Range($sheet.Cells.Item($r,1),$sheet.Cells.Item($r,$last))
            $range.Font.Bold=$true
            $range.Borders.Item(8).LineStyle=1
            $range.Borders.Item(8).Weight=2
        }
        $sheet.Columns.Item('A').WrapText=$true
        $sheet.UsedRange.Rows.AutoFit() | Out-Null
        $sheet.Rows.Item(1).RowHeight=30
        $sheet.Rows.Item(2).RowHeight=32
        $sheet.Rows.Item(3).RowHeight=42
    }
    $income=$book.Worksheets.Item('Income')
    $noteRow=$income.UsedRange.Rows.Count
    $income.Range($income.Cells.Item($noteRow,1),$income.Cells.Item($noteRow,$income.UsedRange.Columns.Count)).Merge() | Out-Null
    $income.Rows.Item($noteRow).RowHeight=68
    foreach ($name in @('Income','Assets','WorkingCapital','CashFlow')) {
        $sheet=$book.Worksheets.Item($name)
        foreach ($driver in $snapshot.presentation.drivers.PSObject.Properties[$name].Value.PSObject.Properties) {
            $r=[int]$driver.Name
            $range=$sheet.Range($sheet.Cells.Item($r,2),$sheet.Cells.Item($r,$sheet.UsedRange.Columns.Count))
            $range.NumberFormat=if ($name -eq 'Assets' -and $r -in @(16,24)) {'0.0'} else {'0.0%'}
            $range.Font.Italic=$true
        }
    }
    foreach ($r in $snapshot.presentation.income_percent_rows) {
        $income.Rows.Item([int]$r).NumberFormat='0.0%'
    }
    $book.Worksheets.Item('DCF').Rows.Item(37).NumberFormat='0.0%'
    $dcf.Rows.Item(25).WrapText=$true
    $dcf.Rows.Item(25).RowHeight=42
    $dcf.Rows.Item(25).Font.Bold=$true
    $dcf.Range($dcf.Cells.Item(25,1),$dcf.Cells.Item(25,$dcf.UsedRange.Columns.Count)).Interior.Color=15132390
    $dcf.Rows.Item(44).NumberFormat='0.00'
    $formulaErrors=@()
    foreach ($sheet in $book.Worksheets) {
        try { $errors=$sheet.UsedRange.SpecialCells(-4123,16); foreach ($cell in $errors.Cells) { $formulaErrors += "$($sheet.Name)!$($cell.Address()): $($cell.Text)" } } catch { }
    }
    if ($formulaErrors.Count) { throw ($formulaErrors -join '; ') }
    $inputs = $book.Worksheets.Item('Inputs')
    $betaCell = $inputs.Cells.Item([int]$snapshot.input_rows.beta,2)
    $priorBeta = [double]$betaCell.Value2
    $betaCell.Value2 = $priorBeta + 0.1
    $excel.CalculateFullRebuild()
    if ($dcf.Range('B20').Value2 -ne 'EDITED_UNREVIEWED' -or [Math]::Abs([double]$dcf.Range('B19').Value2-$value) -lt 0.000001) { throw 'Native Excel edit invalidation failed' }
    $betaCell.Value2 = $priorBeta
    $excel.CalculateFullRebuild()
    if ([Math]::Abs([double]$dcf.Range('B19').Value2-$value) -gt 0.000001) { throw 'Native restoration changed value' }
    $nativeCostEdit='NOT_APPLICABLE'
    if ($null -ne $snapshot.input_rows.cogs_ratio) {
        $costCell=$inputs.Cells.Item([int]$snapshot.input_rows.cogs_ratio,2)
        $priorCost=[double]$costCell.Value2
        $forecastColumn=[int]$snapshot.presentation.history_columns+3
        $baseEbit=[double]$income.Cells.Item(38,$forecastColumn).Value2
        $revenue=[double]$income.Cells.Item(8,$forecastColumn).Value2
        $costCell.Value2=$priorCost+0.01
        $excel.CalculateFullRebuild()
        $newEbit=[double]$income.Cells.Item(38,$forecastColumn).Value2
        if ([Math]::Abs($baseEbit-$newEbit-$revenue*0.01) -gt 0.000001 -or $dcf.Range('B20').Value2 -ne 'EDITED_UNREVIEWED' -or [double]$dcf.Range('B19').Value2 -ge $value) { throw 'Native expense driver propagation failed' }
        foreach ($item in $snapshot.historical_checks) {
            $actual=$book.Worksheets.Item($item.sheet).Range($item.cell).Value2
            if ($null -eq $actual -or [Math]::Abs([double]$actual-[double]$item.value) -gt 0.000001) { throw 'Expense edit changed history' }
        }
        $costCell.Value2=$priorCost
        $excel.CalculateFullRebuild()
        if ([Math]::Abs([double]$dcf.Range('B19').Value2-$value) -gt 0.000001) { throw 'Expense restoration changed value' }
        $nativeCostEdit='PASS'
    }
    # Lead with the analytical outputs; source and audit tabs remain accessible.
    foreach ($name in @('Sensitivity','DCF','WorkingCapital','Assets','CashFlow','BalanceSheet','Income','Review')) {
        $book.Worksheets.Item($name).Move($book.Worksheets.Item(1))
    }
    $review.Activate()
    $excel.ActiveWindow.ScrollRow = 1
    $excel.ActiveWindow.ScrollColumn = 1
    $book.Save()
    @{ status='PASS'; excel_version=$excel.Version; values_checked=$valuesChecked; operating_values_checked=$operatingChecked; historical_values_checked=$historyChecked; formula_errors=$formulaErrors.Count; maximum_difference=$maximum; per_share_value=$value; native_beta_edit='PASS'; native_cost_edit=$nativeCostEdit; hyperlinks=$review.Hyperlinks.Count } | ConvertTo-Json | Set-Content -LiteralPath $ProofPath -Encoding utf8
} finally {
    if ($null -ne $book) { $book.Close($false) }
    $excel.Quit()
    [System.Runtime.InteropServices.Marshal]::ReleaseComObject($excel) | Out-Null
}
