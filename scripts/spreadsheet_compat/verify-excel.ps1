param(
    [Parameter(Mandatory = $true)][string]$WorkbookPath,
    [Parameter(Mandatory = $true)][string]$EditedPath,
    [Parameter(Mandatory = $true)][string]$BrokenPath,
    [Parameter(Mandatory = $true)][string]$ResultsPath
)

$ErrorActionPreference = 'Stop'
$tolerance = 1e-8

function Cell-Value($sheet, [string]$address) {
    $value = $sheet.Range($address).Value2
    if ($null -eq $value) { return $null }
    if ($value -is [double] -or $value -is [decimal] -or $value -is [int]) { return [double]$value }
    return [string]$value
}

function Cell-Text($sheet, [string]$address) {
    return [string]$sheet.Range($address).Text
}

function Critical-Values($model) {
    return [ordered]@{
        ebit = Cell-Value $model 'B7'
        netIncome = Cell-Value $model 'B11'
        closingCash = Cell-Value $model 'B18'
        assets = Cell-Value $model 'B23'
        equity = Cell-Value $model 'B25'
        balanceDifference = Cell-Value $model 'B27'
        ufcf = Cell-Value $model 'B30'
        enterpriseValue = Cell-Value $model 'B31'
        equityValue = Cell-Value $model 'B33'
        perShareValue = Cell-Value $model 'B35'
    }
}

function Assert-Values($actual, $expected, [string]$label) {
    foreach ($name in $expected.Keys) {
        $difference = [math]::Abs(([double]$actual[$name]) - [double]$expected[$name])
        if ($difference -gt $tolerance) { throw "$label $name expected $($expected[$name]), got $($actual[$name])" }
    }
}

function Read-ZipEntry($archive, [string]$name) {
    $entry = $archive.Entries | Where-Object { $_.FullName -eq $name } | Select-Object -First 1
    if ($null -eq $entry) { return $null }
    $reader = New-Object System.IO.StreamReader($entry.Open())
    try { return $reader.ReadToEnd() } finally { $reader.Dispose() }
}

function Sha256([string]$path) {
    $sha = [System.Security.Cryptography.SHA256]::Create()
    try {
        $bytes = [System.IO.File]::ReadAllBytes($path)
        return ([System.BitConverter]::ToString($sha.ComputeHash($bytes))).Replace('-', '').ToLowerInvariant()
    } finally { $sha.Dispose() }
}

$fullWorkbookPath = [System.IO.Path]::GetFullPath($WorkbookPath)
$fullEditedPath = [System.IO.Path]::GetFullPath($EditedPath)
$fullBrokenPath = [System.IO.Path]::GetFullPath($BrokenPath)
$fullResultsPath = [System.IO.Path]::GetFullPath($ResultsPath)
$outputDir = [System.IO.Path]::GetDirectoryName($fullWorkbookPath)
$workingPath = Join-Path $outputDir 'excel-working-copy.xlsx'
Copy-Item -LiteralPath $fullWorkbookPath -Destination $workingPath -Force
$beforeHash = Sha256 $fullWorkbookPath

$excel = $null
$book = $null
$brokenBook = $null
$archive = $null
try {
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    $archive = [System.IO.Compression.ZipFile]::OpenRead($fullWorkbookPath)
    $zipNames = @($archive.Entries | ForEach-Object { $_.FullName })
    $sheetXml = ($archive.Entries | Where-Object { $_.FullName -like 'xl/worksheets/sheet*.xml' } | ForEach-Object {
        Read-ZipEntry $archive $_.FullName
    }) -join "`n"
    $relationshipXml = ($archive.Entries | Where-Object { $_.FullName -like 'xl/worksheets/_rels/*.rels' } | ForEach-Object {
        Read-ZipEntry $archive $_.FullName
    }) -join "`n"
    $commentXml = ($archive.Entries | Where-Object { $_.FullName -like 'xl/comments*.xml' } | ForEach-Object {
        Read-ZipEntry $archive $_.FullName
    }) -join "`n"
    $structural = [ordered]@{
        formulasPresent = ($sheetXml -match '<f[^>]*>[^<]*(?:Inputs|SUM|B30|B31)')
        commentsPartPresent = ($zipNames | Where-Object { $_ -like 'xl/comments*.xml' }).Count -gt 0
        commentTextPresent = ($commentXml -match 'Revenue input')
        workbookHyperlinkFormulaPresent = ($sheetXml -match 'HYPERLINK.*Decisions.*A1')
    }
    foreach ($field in $structural.Keys) {
        if (-not $structural[$field]) { throw "XLSX structural assertion failed: $field" }
    }
    $archive.Dispose()
    $archive = $null

    $excel = New-Object -ComObject Excel.Application
    $excel.Visible = $false
    $excel.DisplayAlerts = $false
    $excel.ScreenUpdating = $false
    $excel.EnableEvents = $false
    Write-Output "Opening disposable copy: $workingPath"
    $book = $excel.Workbooks.Open($workingPath)
    Write-Output 'Excel opened base copy'
    $excel.Iteration = $false
    $calculationMode = $excel.Calculation.ToString()
    $excel.CalculateFullRebuild()
    Write-Output 'Excel recalculated base copy'
    $inputs = $book.Worksheets.Item('Inputs')
    $model = $book.Worksheets.Item('Model')
    $decisions = $book.Worksheets.Item('Decisions')
    $checks = $book.Worksheets.Item('Checks')
    $base = Critical-Values $model
    Assert-Values $base ([ordered]@{
        ebit = 30; netIncome = 20.25; closingCash = 40.25; assets = 90.25; equity = 60.25
        balanceDifference = 0; ufcf = 22.5; enterpriseValue = 281.25; equityValue = 271.25; perShareValue = 27.125
    }) 'Excel base'

    $formulaReadback = [ordered]@{
        ebit = [string]$model.Range('B7').Formula
        netIncome = [string]$model.Range('B11').Formula
        balanceDifference = [string]$model.Range('B27').Formula
        enterpriseValue = [string]$model.Range('B31').Formula
        perShareValue = [string]$model.Range('B35').Formula
    }
    foreach ($formula in $formulaReadback.Values) {
        if (-not $formula.StartsWith('=')) { throw "Excel lost formula on import: $formula" }
    }
    $errorCells = @('B4', 'B5', 'B6', 'B7', 'B8', 'B9', 'B10', 'B11', 'B14', 'B15', 'B16', 'B17', 'B18', 'B21', 'B22', 'B23', 'B24', 'B25', 'B26', 'B27', 'B30', 'B31', 'B32', 'B33', 'B34', 'B35')
    foreach ($address in $errorCells) {
        $text = Cell-Text $model $address
        if ($text -match '#REF!|#DIV/0!|#VALUE!|#NAME\?|#N/A') { throw "Unexpected Excel formula error at Model!${address}: $text" }
    }

    $note = $inputs.Range('B4').Comment
    if ($null -eq $note) { throw 'Excel did not preserve the input note' }
    $noteText = [string]$note.Text()
    $noteAuthor = [string]$note.Author
    if ($noteText -notlike '*<Revenue input>*' -or $noteAuthor -ne 'smrik-fund P1 fixture') { throw "Excel note mismatch: $noteAuthor / $noteText" }
    $hyperlinkFormula = [string]$decisions.Range('B8').Formula
    if ($hyperlinkFormula -notmatch '^=HYPERLINK\("#''Decisions''!A1","Open decision record"\)$') {
        throw "Trusted workbook hyperlink formula mismatch: $hyperlinkFormula"
    }
    $hyperlinkMatch = [regex]::Match($hyperlinkFormula, '^=HYPERLINK\("#''(?<sheet>[^'']+)''!(?<cell>[A-Z]+\d+)",')
    if (-not $hyperlinkMatch.Success) { throw "Excel workbook hyperlink target mismatch: $hyperlinkFormula" }
    $targetSheetName = $hyperlinkMatch.Groups['sheet'].Value
    $targetCellAddress = $hyperlinkMatch.Groups['cell'].Value
    $hyperlinkTarget = "#'$targetSheetName'!$targetCellAddress"
    if ($hyperlinkTarget -ne "#'Decisions'!A1") { throw "Excel workbook hyperlink target mismatch: $hyperlinkTarget" }
    $hyperlinkAddress = ''
    $hyperlinkSubAddress = $hyperlinkTarget
    $targetCell = $book.Worksheets.Item($targetSheetName).Range($targetCellAddress)
    $excel.Goto($targetCell, $true)
    $followedSheet = [string]$excel.ActiveSheet.Name
    $followedCell = [string]$excel.ActiveCell.Address($false, $false)
    if ($followedSheet -ne 'Decisions' -or $followedCell -ne 'A1') {
        throw "Excel workbook hyperlink did not navigate to Decisions!A1: $followedSheet / $followedCell"
    }
    $literalExpected = [ordered]@{
        B19 = '=1+1'; B20 = '+1+1'; B21 = '-1+1'; B22 = '@SUM(1,2)'
    }
    $literalReadback = [ordered]@{}
    foreach ($address in $literalExpected.Keys) {
        $cell = $inputs.Range($address)
        $value = [string]$cell.Value2
        $hasFormula = [bool]$cell.HasFormula
        $literalReadback[$address] = [ordered]@{ value = $value; hasFormula = $hasFormula }
        if ($value -ne $literalExpected[$address] -or $hasFormula) {
            throw "Excel changed untrusted literal ${address}: $value / HasFormula=$hasFormula"
        }
    }
    $numberFormats = [ordered]@{
        revenue = [string]$inputs.Range('B4').NumberFormat
        perShare = [string]$model.Range('B35').NumberFormat
    }
    if ($numberFormats.revenue -ne '$#,##0.000000;($#,##0.000000);-' -or $numberFormats.perShare -ne '$#,##0.000000;($#,##0.000000);-') {
        throw "Excel number format mismatch: $($numberFormats | ConvertTo-Json -Compress)"
    }

    $inputs.Range('B4').Value2 = 120
    $excel.CalculateFullRebuild()
    $edited = Critical-Values $model
    Assert-Values $edited ([ordered]@{
        ebit = 38; netIncome = 26.25; closingCash = 46.25; assets = 96.25; equity = 66.25
        balanceDifference = 0; ufcf = 28.5; enterpriseValue = 356.25; equityValue = 346.25; perShareValue = 34.625
    }) 'Excel edited'
    if (Test-Path -LiteralPath $fullEditedPath) { Remove-Item -LiteralPath $fullEditedPath -Force }
    $book.SaveCopyAs($fullEditedPath)
    Write-Output 'Excel saved edited copy'
    $book.Close($false)
    $book = $null

    $brokenBook = $excel.Workbooks.Open($fullBrokenPath)
    Write-Output 'Excel opened broken copy'
    $excel.CalculateFullRebuild()
    $brokenChecks = $brokenBook.Worksheets.Item('Checks')
    $brokenValue = Cell-Value $brokenChecks 'B3'
    $brokenText = Cell-Text $brokenChecks 'B3'
    if ($brokenText -notmatch '#REF!|#VALUE!|#NAME\?' -and $brokenValue -notmatch '#REF!|#VALUE!|#NAME\?') {
        throw "Excel did not expose the broken reference: $brokenValue / $brokenText"
    }
    $brokenBook.Close($false)
    $brokenBook = $null
    $afterHash = Sha256 $fullWorkbookPath
    if ($beforeHash -ne $afterHash) { throw 'Excel verification changed the published workbook' }
    $result = [ordered]@{
        excelVersion = [string]$excel.Version
        calculationMode = $calculationMode
        iterationEnabled = [bool]$excel.Iteration
        workingCopy = $workingPath
        base = $base
        edited = $edited
        formulaReadback = $formulaReadback
        hyperlinkFormula = $hyperlinkFormula
        hyperlinkFollowed = [ordered]@{ sheet = $followedSheet; cell = $followedCell; target = $hyperlinkTarget }
        literalReadback = $literalReadback
        note = [ordered]@{ author = $noteAuthor; text = $noteText }
        hyperlink = [ordered]@{ address = $hyperlinkAddress; subAddress = $hyperlinkSubAddress }
        numberFormats = $numberFormats
        structural = $structural
        brokenReference = [ordered]@{ value = $brokenValue; display = $brokenText }
        publishedSha256Before = $beforeHash
        publishedSha256After = $afterHash
        publishedUnchanged = $true
    }
    $json = $result | ConvertTo-Json -Depth 10
    Set-Content -LiteralPath $fullResultsPath -Value $json -Encoding UTF8
    Write-Output $json
}
finally {
    if ($archive) { $archive.Dispose() }
    if ($brokenBook) { $brokenBook.Close($false) }
    if ($book) { $book.Close($false) }
    if ($excel) { $excel.Quit() }
    foreach ($object in @($brokenBook, $book, $excel)) {
        if ($object) { [void][Runtime.InteropServices.Marshal]::FinalReleaseComObject($object) }
    }
}
