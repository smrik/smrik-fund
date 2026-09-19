param(
    [Parameter(Mandatory = $true)][string]$WorkbookPath,
    [Parameter(Mandatory = $true)][string]$EditedPath,
    [Parameter(Mandatory = $true)][string]$BrokenPath,
    [Parameter(Mandatory = $true)][string]$ResultsPath,
    [Parameter(Mandatory = $true)][string]$ExpectationsPath
)

$ErrorActionPreference = 'Stop'
$tolerance = 1e-8
$requiredInputCount = 33
$requiredInputAddresses = @(
    'B6', 'B7', 'B8', 'B9', 'B10', 'B11', 'B12',
    'B17', 'B18', 'B19', 'B20', 'B21', 'B22', 'B23', 'B24', 'B25', 'B26', 'B27', 'B28', 'B29', 'B30', 'B31',
    'B35', 'C35', 'D35', 'E35', 'F35', 'G35', 'H35', 'I35', 'J35', 'K35', 'L35'
)
$allColumns = @('B', 'C', 'D', 'E', 'F', 'G', 'H', 'I', 'J', 'K', 'L')

function Cell-Value($sheet, [string]$address) {
    $value = $sheet.Range($address).Value2
    if ($null -eq $value) { return $null }
    if ($value -is [double] -or $value -is [decimal] -or $value -is [int] -or $value -is [long]) { return [double]$value }
    return [string]$value
}

function Cell-Text($sheet, [string]$address) {
    return [string]$sheet.Range($address).Text
}

function Assert-Close($actual, $expected, [string]$label) {
    $difference = [math]::Abs(([double]$actual) - ([double]$expected))
    if ($difference -gt $tolerance) { throw "$label expected $expected, got $actual" }
}

function Critical-Values($book, [string]$column) {
    $income = $book.Worksheets.Item('Income')
    $schedules = $book.Worksheets.Item('Schedules')
    $cashFlow = $book.Worksheets.Item('CashFlow')
    $balanceSheet = $book.Worksheets.Item('BalanceSheet')
    $dcf = $book.Worksheets.Item('DCF')
    return [ordered]@{
        revenue = Cell-Value $income "${column}6"
        cashOperatingCosts = Cell-Value $income "${column}7"
        depreciation = Cell-Value $income "${column}8"
        ebit = Cell-Value $income "${column}9"
        interestExpense = Cell-Value $income "${column}10"
        netIncome = Cell-Value $income "${column}13"
        capex = Cell-Value $schedules "${column}12"
        closingCash = Cell-Value $cashFlow "${column}17"
        closingNetPPE = Cell-Value $balanceSheet "${column}9"
        closingEquity = Cell-Value $balanceSheet "${column}13"
        assets = Cell-Value $balanceSheet "${column}10"
        balanceDifference = Cell-Value $balanceSheet "${column}15"
        closingAR = Cell-Value $schedules "${column}20"
        closingInventory = Cell-Value $schedules "${column}22"
        closingAP = Cell-Value $schedules "${column}24"
        increaseNWC = Cell-Value $schedules "${column}27"
        cfo = Cell-Value $cashFlow "${column}9"
        dividends = Cell-Value $schedules "${column}29"
        ufcf = Cell-Value $dcf "${column}7"
        enterpriseValue = Cell-Value $dcf 'B15'
        equityValue = Cell-Value $dcf 'B18'
        perShareValue = Cell-Value $dcf 'B20'
    }
}

function Assert-Snapshot($actual, $expected, [string]$label) {
    $names = @('revenue', 'cashOperatingCosts', 'depreciation', 'ebit', 'interestExpense', 'netIncome', 'capex', 'closingCash', 'closingNetPPE', 'closingEquity', 'assets', 'balanceDifference', 'closingAR', 'closingInventory', 'closingAP', 'increaseNWC', 'cfo', 'dividends', 'ufcf', 'enterpriseValue', 'equityValue', 'perShareValue')
    foreach ($name in $names) { Assert-Close $actual[$name] $expected.$name "$label.$name" }
}

function Input-Gate($book) {
    $inputs = $book.Worksheets.Item('Inputs')
    $review = $book.Worksheets.Item('Review')
    $dcf = $book.Worksheets.Item('DCF')
    $checks = $book.Worksheets.Item('Checks')
    return [ordered]@{
        count = Cell-Value $inputs 'B34'
        status = Cell-Text $inputs 'B33'
        reviewStatus = Cell-Text $review 'B3'
        requiredCondition = Cell-Text $dcf 'B23'
        valuationStatus = Cell-Text $dcf 'B24'
        enterpriseValue = Cell-Value $dcf 'B15'
        equityValue = Cell-Value $dcf 'B18'
        perShareValue = Cell-Value $dcf 'B20'
        overall = @($allColumns | ForEach-Object { Cell-Text $checks "${_}20" })
        requiredChecks = @($allColumns | ForEach-Object { Cell-Text $checks "${_}21" })
    }
}

function Assert-Gate($gate, [string]$expectedStatus, [string]$label) {
    $expectedReview = if ($expectedStatus -eq 'PASS') { 'READY' } else { 'BLOCKED' }
    $expectedOverall = if ($expectedStatus -eq 'PASS') { 'PASS' } else { 'FAIL' }
    $expectedValuation = if ($expectedStatus -eq 'PASS') { 'AVAILABLE' } else { 'BLOCKED' }
    if ($gate.status -ne $expectedStatus) { throw "$label Inputs!B33 expected $expectedStatus, got $($gate.status)" }
    if ($gate.requiredCondition -ne $expectedStatus) { throw "$label DCF!B23 expected $expectedStatus, got $($gate.requiredCondition)" }
    if ($gate.reviewStatus -ne $expectedReview) { throw "$label Review!B3 expected $expectedReview, got $($gate.reviewStatus)" }
    if ($gate.valuationStatus -ne $expectedValuation) { throw "$label DCF!B24 expected $expectedValuation, got $($gate.valuationStatus)" }
    if (@($gate.overall | Where-Object { $_ -ne $expectedOverall }).Count -gt 0) { throw "$label overall checks: $($gate.overall -join ',')" }
    if (@($gate.requiredChecks | Where-Object { $_ -ne $expectedOverall }).Count -gt 0) { throw "$label required checks: $($gate.requiredChecks -join ',')" }
}

function Assert-Blocked-Valuation($gate, [string]$label) {
    foreach ($name in @('enterpriseValue', 'equityValue', 'perShareValue')) {
        if ([string]$gate[$name] -ne 'BLOCKED') { throw "$label DCF valuation $name was not blocked: $($gate[$name])" }
    }
}

function Sha256([string]$path) {
    $sha = [System.Security.Cryptography.SHA256]::Create()
    try {
        $bytes = [System.IO.File]::ReadAllBytes($path)
        return ([System.BitConverter]::ToString($sha.ComputeHash($bytes))).Replace('-', '').ToLowerInvariant()
    } finally { $sha.Dispose() }
}

function Assert-Formula($sheet, [string]$address, [string]$label) {
    $formula = [string]$sheet.Range($address).Formula
    if (-not $formula.StartsWith('=')) { throw "$label lost formula: $formula" }
    return $formula
}

$fullWorkbookPath = [System.IO.Path]::GetFullPath($WorkbookPath)
$fullEditedPath = [System.IO.Path]::GetFullPath($EditedPath)
$fullBrokenPath = [System.IO.Path]::GetFullPath($BrokenPath)
$fullResultsPath = [System.IO.Path]::GetFullPath($ResultsPath)
$expectations = Get-Content -LiteralPath ([System.IO.Path]::GetFullPath($ExpectationsPath)) -Raw | ConvertFrom-Json
$outputDir = [System.IO.Path]::GetDirectoryName($fullWorkbookPath)
$workingPath = Join-Path $outputDir 'excel-working-copy.xlsx'
[System.IO.File]::Copy($fullWorkbookPath, $workingPath, $true)
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
        $reader = New-Object System.IO.StreamReader($_.Open())
        try { $reader.ReadToEnd() } finally { $reader.Dispose() }
    }) -join "`n"
    $archive.Dispose()
    $archive = $null
    if ($zipNames.Count -eq 0 -or $sheetXml -notmatch '<f[^>]*>') { throw 'XLSX structural assertion failed: formulas missing' }
    $structural = [ordered]@{ worksheetParts = $zipNames.Count; formulasPresent = $true }

    $excel = New-Object -ComObject Excel.Application
    $excel.Visible = $false
    $excel.DisplayAlerts = $false
    $excel.ScreenUpdating = $false
    $excel.EnableEvents = $false
    $book = $excel.Workbooks.Open($workingPath)
    $excel.Iteration = $false
    $calculationMode = $excel.Calculation.ToString()
    $excel.CalculateFullRebuild()
    Write-Output 'Excel recalculated base fictional model'

    $inputs = $book.Worksheets.Item('Inputs')
    $schedules = $book.Worksheets.Item('Schedules')
    $income = $book.Worksheets.Item('Income')
    $dcf = $book.Worksheets.Item('DCF')
    $checks = $book.Worksheets.Item('Checks')
    $baseStub = Critical-Values $book 'B'
    $baseFirstFull = Critical-Values $book 'C'
    Assert-Snapshot $baseStub $expectations.base.stub 'Excel base stub'
    Assert-Snapshot $baseFirstFull $expectations.base.firstFull 'Excel base first full year'
    $baseGate = Input-Gate $book
    Assert-Gate $baseGate 'PASS' 'Excel base'
    if ([double]$baseGate.count -ne $requiredInputCount) { throw "Excel base required input count mismatch: $($baseGate.count)" }
    $inputFormula = Assert-Formula $inputs 'B34' 'Inputs!B34'
    foreach ($address in $requiredInputAddresses) {
        if ($inputFormula -notmatch [regex]::Escape("ISNUMBER($address)")) { throw "Inputs!B34 omitted $address" }
    }
    $formulaReadback = [ordered]@{
        ebit = Assert-Formula $income 'B9' 'Income!B9'
        netIncome = Assert-Formula $income 'C13' 'Income!C13'
        ufcf = Assert-Formula $dcf 'B7' 'DCF!B7'
        enterpriseValue = Assert-Formula $dcf 'B15' 'DCF!B15'
        perShareValue = Assert-Formula $dcf 'B20' 'DCF!B20'
        balanceCheck = Assert-Formula $checks 'B6' 'Checks!B6'
    }
    if ($formulaReadback.balanceCheck -notmatch 'ABS\(B5\).*(1E-0?8|0\.00000001)') { throw "Checks!B6 lost declared 1e-8 tolerance: $($formulaReadback.balanceCheck)" }

    [void]$inputs.Range('B21').ClearContents()
    $excel.CalculateFullRebuild()
    $clearCapexGate = Input-Gate $book
    $clearCapexValues = Critical-Values $book 'B'
    Assert-Gate $clearCapexGate 'FAIL' 'Excel clear capex'
    if ([double]$clearCapexGate.count -ne $requiredInputCount - 1) { throw "Excel clear capex count mismatch: $($clearCapexGate.count)" }
    Assert-Close (Cell-Value $schedules 'B12') 0 'Excel clear capex schedule'
    Assert-Close $clearCapexValues.ufcf 8.125 'Excel clear capex stub UFCF'
    Assert-Blocked-Valuation $clearCapexGate 'Excel clear capex'
    $clearCapex = [ordered]@{ gate = $clearCapexGate; capex = Cell-Value $schedules 'B12'; stubUfcf = $clearCapexValues.ufcf }
    Write-Output 'Excel blocked missing capex input'

    $inputs.Range('B21').Value2 = 0
    $excel.CalculateFullRebuild()
    $zeroCapexGate = Input-Gate $book
    Assert-Gate $zeroCapexGate 'PASS' 'Excel valid zero capex'
    Assert-Close (Cell-Value $schedules 'B12') 0 'Excel valid zero capex schedule'
    if (-not ($zeroCapexGate.enterpriseValue -is [double])) { throw "Excel valid zero capex valuation was not numeric: $($zeroCapexGate.enterpriseValue)" }
    $zeroCapex = [ordered]@{ gate = $zeroCapexGate; capex = Cell-Value $schedules 'B12'; enterpriseValue = $zeroCapexGate.enterpriseValue }
    Write-Output 'Excel accepted numeric zero capex input'

    $inputs.Range('B21').Value2 = 0.1
    [void]$inputs.Range('B24').ClearContents()
    $excel.CalculateFullRebuild()
    $clearTaxGate = Input-Gate $book
    $clearTaxValues = Critical-Values $book 'B'
    Assert-Gate $clearTaxGate 'FAIL' 'Excel clear tax'
    if ([double]$clearTaxGate.count -ne $requiredInputCount - 1) { throw "Excel clear tax count mismatch: $($clearTaxGate.count)" }
    Assert-Close (Cell-Value $schedules 'B28') 0 'Excel clear tax schedule'
    Assert-Close $clearTaxValues.ufcf 7.5 'Excel clear tax stub UFCF'
    Assert-Blocked-Valuation $clearTaxGate 'Excel clear tax'
    $clearTax = [ordered]@{ gate = $clearTaxGate; tax = Cell-Value $schedules 'B28'; stubUfcf = $clearTaxValues.ufcf }
    Write-Output 'Excel blocked missing tax input'

    $inputs.Range('B24').Value2 = 0.25
    $inputs.Range('C35').NumberFormat = '@'
    $inputs.Range('C35').Value2 = '0'
    $excel.CalculateFullRebuild()
    $textRevenueGate = Input-Gate $book
    $textRevenueValues = Critical-Values $book 'C'
    Assert-Gate $textRevenueGate 'FAIL' 'Excel text revenue'
    if ([double]$textRevenueGate.count -ne $requiredInputCount - 1) { throw "Excel text revenue count mismatch: $($textRevenueGate.count)" }
    if ((Cell-Text $inputs 'C35') -ne '0' -or [bool]$inputs.Range('C35').HasFormula) { throw 'Excel text revenue was not preserved as text' }
    Assert-Close $textRevenueValues.revenue 0 'Excel text revenue link'
    Assert-Blocked-Valuation $textRevenueGate 'Excel text revenue'
    $textRevenue = [ordered]@{ gate = $textRevenueGate; input = Cell-Text $inputs 'C35'; revenue = $textRevenueValues.revenue; hasFormula = [bool]$inputs.Range('C35').HasFormula }
    Write-Output 'Excel blocked number-formatted-as-text revenue input'

    $inputs.Range('B21').Value2 = 0.1
    $inputs.Range('C35').NumberFormat = '#,##0.000000;(#,##0.000000);-'
    $inputs.Range('C35').Formula = '=B35/B18*(1+B20)'
    $excel.CalculateFullRebuild()
    $recoveryGate = Input-Gate $book
    $recoveryStub = Critical-Values $book 'B'
    $recoveryFirstFull = Critical-Values $book 'C'
    Assert-Gate $recoveryGate 'PASS' 'Excel recovery'
    Assert-Snapshot $recoveryStub $expectations.base.stub 'Excel recovery stub'
    Assert-Snapshot $recoveryFirstFull $expectations.base.firstFull 'Excel recovery first full year'
    $recovery = [ordered]@{ gate = $recoveryGate; stub = $recoveryStub; firstFull = $recoveryFirstFull }
    $book.SaveCopyAs($fullEditedPath)
    Write-Output 'Excel recovered inputs and saved edited fictional workbook copy'
    $book.Close($false)
    $book = $null

    $brokenBook = $excel.Workbooks.Open($fullBrokenPath)
    $excel.CalculateFullRebuild()
    $brokenSchedule = $brokenBook.Worksheets.Item('Schedules')
    $brokenValue = Cell-Value $brokenSchedule 'B38'
    $brokenText = Cell-Text $brokenSchedule 'B38'
    if ($brokenText -notmatch '#REF!|#NAME\?|#VALUE!' -and [string]$brokenValue -notmatch '#REF!|#NAME\?|#VALUE!') {
        throw "Excel did not expose the broken reference: $brokenValue / $brokenText"
    }
    $brokenBook.Close($false)
    $brokenBook = $null
    $afterHash = Sha256 $fullWorkbookPath
    if ($beforeHash -ne $afterHash) { throw 'Excel verification changed the published fictional workbook' }
    $result = [ordered]@{
        excelVersion = [string]$excel.Version
        calculationMode = $calculationMode
        iterationEnabled = [bool]$excel.Iteration
        workingCopy = $workingPath
        base = [ordered]@{ stub = $baseStub; firstFull = $baseFirstFull; gate = $baseGate }
        formulaReadback = $formulaReadback
        inputFormula = $inputFormula
        mutations = [ordered]@{ clearCapex = $clearCapex; zeroCapex = $zeroCapex; clearTax = $clearTax; textRevenue = $textRevenue; recovery = $recovery }
        structural = $structural
        brokenReference = [ordered]@{ value = $brokenValue; display = $brokenText }
        publishedSha256Before = $beforeHash
        publishedSha256After = $afterHash
        publishedUnchanged = $true
    }
    $json = $result | ConvertTo-Json -Depth 15
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
