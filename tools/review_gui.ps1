param(
    [string]$Config = "config.example.yml",
    [string]$Python = "python"
)

$ErrorActionPreference = "Stop"

$Utf8NoBom = New-Object System.Text.UTF8Encoding($false)
[Console]::InputEncoding = $Utf8NoBom
[Console]::OutputEncoding = $Utf8NoBom
$OutputEncoding = $Utf8NoBom
$env:PYTHONIOENCODING = "utf-8"
$env:PYTHONUTF8 = "1"

Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing

$ProjectRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$ArchiveScript = Join-Path $ProjectRoot "archive_pdf.py"
if ([System.IO.Path]::IsPathRooted($Config)) {
    $ConfigPath = $Config
} else {
    $ConfigPath = Join-Path $ProjectRoot $Config
}

function Invoke-Archive {
    param([string[]]$ArgsList)

    $stderrPath = [System.IO.Path]::GetTempFileName()
    try {
        $output = & $Python $ArchiveScript @ArgsList 2> $stderrPath
        $exitCode = $LASTEXITCODE
        $stderr = ""
        if (Test-Path -LiteralPath $stderrPath) {
            $stderr = Get-Content -LiteralPath $stderrPath -Raw -Encoding UTF8
        }
        if ($exitCode -ne 0) {
            $stdout = ($output | ForEach-Object { $_.ToString() }) -join "`r`n"
            $details = (($stderr, $stdout) | Where-Object { $_ }) -join "`r`n"
            if ($details) {
                throw "archive_pdf.py failed with exit code $exitCode.`r`n`r`n$details"
            }
            throw "archive_pdf.py failed with exit code $exitCode."
        }
        return ($output -join "`r`n")
    } finally {
        Remove-Item -LiteralPath $stderrPath -Force -ErrorAction SilentlyContinue
    }
}

function Add-OptionalArg {
    param(
        [System.Collections.ArrayList]$ArgsList,
        [string]$Name,
        [string]$Value
    )

    if (-not [string]::IsNullOrWhiteSpace($Value)) {
        [void]$ArgsList.Add($Name)
        [void]$ArgsList.Add($Value.Trim())
    }
}

function Add-Label {
    param(
        [System.Windows.Forms.Form]$Form,
        [string]$Text,
        [int]$X,
        [int]$Y,
        [int]$Width = 120
    )
    $label = New-Object System.Windows.Forms.Label
    $label.Text = $Text
    $label.Location = New-Object System.Drawing.Point($X, $Y)
    $label.Size = New-Object System.Drawing.Size($Width, 22)
    $Form.Controls.Add($label)
    return $label
}

function Add-TextBox {
    param(
        [System.Windows.Forms.Form]$Form,
        [int]$X,
        [int]$Y,
        [int]$Width = 420
    )
    $box = New-Object System.Windows.Forms.TextBox
    $box.Location = New-Object System.Drawing.Point($X, $Y)
    $box.Size = New-Object System.Drawing.Size($Width, 22)
    $Form.Controls.Add($box)
    return $box
}

function Refresh-Queue {
    $json = Invoke-Archive @("--config", $ConfigPath, "--list-review-queue", "--json")
    $script:Snapshot = $json | ConvertFrom-Json
    $script:Items = @($script:Snapshot.items)
    $script:Categories = @($script:Snapshot.categories)
    if ($script:Index -ge $script:Items.Count) {
        $script:Index = [Math]::Max(0, $script:Items.Count - 1)
    }
}

function Rebuild-Categories {
    $categoryCombo.Items.Clear()
    foreach ($category in $script:Categories) {
        $item = [pscustomobject]@{
            Id = $category.id
            Name = $category.name
            Label = "$($category.folder) - $($category.name)"
        }
        [void]$categoryCombo.Items.Add($item)
    }
    [void]$categoryCombo.Items.Add([pscustomobject]@{
        Id = "__custom__"
        Name = "Neue Kategorie"
        Label = "Neue Kategorie..."
    })
    $categoryCombo.DisplayMember = "Label"
}

function Select-Category {
    param([string]$CategoryId, [string]$CategoryName)

    for ($i = 0; $i -lt $categoryCombo.Items.Count; $i++) {
        if ($categoryCombo.Items[$i].Id -eq $CategoryId) {
            $categoryCombo.SelectedIndex = $i
            $customCategoryText.Text = ""
            return
        }
    }
    $categoryCombo.SelectedIndex = $categoryCombo.Items.Count - 1
    $customCategoryText.Text = $CategoryName
}

function Select-SourceType {
    param([string]$SourceType)

    for ($i = 0; $i -lt $sourceTypeCombo.Items.Count; $i++) {
        if ($sourceTypeCombo.Items[$i].Id -eq $SourceType) {
            $sourceTypeCombo.SelectedIndex = $i
            return
        }
    }
    $sourceTypeCombo.SelectedIndex = 2
}

function Set-Form-Enabled {
    param([bool]$Enabled)

    $dateText.Enabled = $Enabled
    $barcodeText.Enabled = $Enabled
    $archiveCodeText.Enabled = $Enabled
    $sourceTypeCombo.Enabled = $Enabled
    $categoryCombo.Enabled = $Enabled
    $customCategoryText.Enabled = $Enabled
    $senderText.Enabled = $Enabled
    $titleText.Enabled = $Enabled
    $shortTitleText.Enabled = $Enabled
    $approveButton.Enabled = $Enabled
    $skipButton.Enabled = $Enabled
    $openButton.Enabled = $Enabled
}

function Load-CurrentItem {
    if ($script:Items.Count -eq 0) {
        $fileLabel.Text = "Keine Dokumente in der Review-Warteschlange."
        $countLabel.Text = "0 / 0"
        $dateText.Text = ""
        $barcodeText.Text = ""
        $archiveCodeText.Text = ""
        $senderText.Text = ""
        $titleText.Text = ""
        $shortTitleText.Text = ""
        $customCategoryText.Text = ""
        $reasonText.Text = ""
        $excerptText.Text = ""
        Set-Form-Enabled $false
        return
    }

    Set-Form-Enabled $true
    $item = $script:Items[$script:Index]
    $fileLabel.Text = "Datei: $($item.original_filename)"
    $countLabel.Text = "$($script:Index + 1) / $($script:Items.Count)"
    $dateText.Text = $item.document_date
    $barcodeText.Text = $item.barcode
    $archiveCode = [string]$item.archive_code
    if ([string]::IsNullOrWhiteSpace($archiveCode) -and -not [string]::IsNullOrWhiteSpace([string]$item.barcode)) {
        $archiveCode = [string]$item.barcode
    }
    $archiveCodeText.Text = $archiveCode
    $sourceType = [string]$item.source_type
    if ([string]::IsNullOrWhiteSpace($sourceType) -or $sourceType -eq "unknown") {
        if ([string]::IsNullOrWhiteSpace([string]$item.barcode)) {
            $sourceType = "digital"
        } else {
            $sourceType = "paper_scan"
        }
    }
    Select-SourceType $sourceType
    $senderText.Text = $item.sender
    $titleText.Text = $item.title
    $shortTitleText.Text = $item.short_filename_title
    Select-Category $item.category_id $item.category_name
    $reasonText.Text = (@($item.review_reasons) -join ", ")
    $excerptText.Text = $item.text_excerpt
}

[System.Windows.Forms.Application]::EnableVisualStyles()

$script:Index = 0
Refresh-Queue

$form = New-Object System.Windows.Forms.Form
$form.Text = "PDF Review & Rename"
$form.StartPosition = "CenterScreen"
$form.Size = New-Object System.Drawing.Size(820, 700)
$form.MinimumSize = New-Object System.Drawing.Size(760, 640)

$fileLabel = Add-Label $form "Datei:" 14 14 600
$countLabel = Add-Label $form "" 690 14 90

Add-Label $form "Datum (YYYY-MM-DD)" 14 52 150 | Out-Null
$dateText = Add-TextBox $form 180 50 160

Add-Label $form "Barcode" 14 84 150 | Out-Null
$barcodeText = Add-TextBox $form 180 82 420

Add-Label $form "Archivcode" 14 116 150 | Out-Null
$archiveCodeText = Add-TextBox $form 180 114 420

Add-Label $form "Dokumenttyp" 14 148 150 | Out-Null
$sourceTypeCombo = New-Object System.Windows.Forms.ComboBox
$sourceTypeCombo.Location = New-Object System.Drawing.Point(180, 146)
$sourceTypeCombo.Size = New-Object System.Drawing.Size(200, 24)
$sourceTypeCombo.DropDownStyle = "DropDownList"
[void]$sourceTypeCombo.Items.Add([pscustomobject]@{ Id = "paper_scan"; Label = "Papier / Scan" })
[void]$sourceTypeCombo.Items.Add([pscustomobject]@{ Id = "digital"; Label = "Digital" })
[void]$sourceTypeCombo.Items.Add([pscustomobject]@{ Id = "unknown"; Label = "Unbekannt" })
$sourceTypeCombo.DisplayMember = "Label"
$form.Controls.Add($sourceTypeCombo)

Add-Label $form "Kategorie" 14 180 150 | Out-Null
$categoryCombo = New-Object System.Windows.Forms.ComboBox
$categoryCombo.Location = New-Object System.Drawing.Point(180, 178)
$categoryCombo.Size = New-Object System.Drawing.Size(420, 24)
$categoryCombo.DropDownStyle = "DropDownList"
$form.Controls.Add($categoryCombo)

Add-Label $form "Neue Kategorie" 14 212 150 | Out-Null
$customCategoryText = Add-TextBox $form 180 210 420

Add-Label $form "Absender" 14 244 150 | Out-Null
$senderText = Add-TextBox $form 180 242 420

Add-Label $form "Titel" 14 276 150 | Out-Null
$titleText = Add-TextBox $form 180 274 420

Add-Label $form "Dateiname-Kurztext" 14 308 150 | Out-Null
$shortTitleText = Add-TextBox $form 180 306 420

Add-Label $form "Review-Gründe" 14 346 150 | Out-Null
$reasonText = New-Object System.Windows.Forms.TextBox
$reasonText.Location = New-Object System.Drawing.Point(180, 344)
$reasonText.Size = New-Object System.Drawing.Size(580, 48)
$reasonText.Multiline = $true
$reasonText.ReadOnly = $true
$form.Controls.Add($reasonText)

Add-Label $form "Textauszug" 14 408 150 | Out-Null
$excerptText = New-Object System.Windows.Forms.TextBox
$excerptText.Location = New-Object System.Drawing.Point(180, 406)
$excerptText.Size = New-Object System.Drawing.Size(580, 120)
$excerptText.Multiline = $true
$excerptText.ScrollBars = "Vertical"
$excerptText.ReadOnly = $true
$form.Controls.Add($excerptText)

$openButton = New-Object System.Windows.Forms.Button
$openButton.Text = "PDF öffnen"
$openButton.Location = New-Object System.Drawing.Point(180, 555)
$openButton.Size = New-Object System.Drawing.Size(105, 30)
$form.Controls.Add($openButton)

$skipButton = New-Object System.Windows.Forms.Button
$skipButton.Text = "Weiter"
$skipButton.Location = New-Object System.Drawing.Point(295, 555)
$skipButton.Size = New-Object System.Drawing.Size(90, 30)
$form.Controls.Add($skipButton)

$approveButton = New-Object System.Windows.Forms.Button
$approveButton.Text = "Übernehmen"
$approveButton.Location = New-Object System.Drawing.Point(395, 555)
$approveButton.Size = New-Object System.Drawing.Size(115, 30)
$form.Controls.Add($approveButton)

$refreshButton = New-Object System.Windows.Forms.Button
$refreshButton.Text = "Aktualisieren"
$refreshButton.Location = New-Object System.Drawing.Point(520, 555)
$refreshButton.Size = New-Object System.Drawing.Size(110, 30)
$form.Controls.Add($refreshButton)

$exitButton = New-Object System.Windows.Forms.Button
$exitButton.Text = "Beenden"
$exitButton.Location = New-Object System.Drawing.Point(640, 555)
$exitButton.Size = New-Object System.Drawing.Size(90, 30)
$form.Controls.Add($exitButton)

$categoryCombo.Add_SelectedIndexChanged({
    $selected = $categoryCombo.SelectedItem
    $customCategoryText.Enabled = ($selected -and $selected.Id -eq "__custom__")
})

function Open-CurrentPdf {
    if ($script:Items.Count -eq 0) { return }

    $pdfPath = [string]$script:Items[$script:Index].pdf_path
    if (-not [System.IO.Path]::IsPathRooted($pdfPath)) {
        $pdfPath = Join-Path $ProjectRoot $pdfPath
    }

    if (-not (Test-Path -LiteralPath $pdfPath -PathType Leaf)) {
        try {
            Refresh-Queue
            Rebuild-Categories
            Load-CurrentItem
        } catch {
            # Keep the original missing-file message below; refresh is only a convenience.
        }
        [System.Windows.Forms.MessageBox]::Show(
            "PDF-Datei wurde nicht gefunden:`r`n$pdfPath`r`n`r`nDie Review-Liste wurde aktualisiert.",
            "PDF nicht gefunden"
        )
        return
    }

    $resolvedPath = (Resolve-Path -LiteralPath $pdfPath).Path
    try {
        Invoke-Item -LiteralPath $resolvedPath
    } catch {
        [System.Windows.Forms.MessageBox]::Show(
            "PDF konnte nicht geöffnet werden:`r`n$resolvedPath`r`n`r`n$($_.Exception.Message)",
            "Fehler"
        )
    }
}

$openButton.Add_Click({
    Open-CurrentPdf
})

$skipButton.Add_Click({
    if ($script:Items.Count -eq 0) { return }
    $script:Index = ($script:Index + 1) % $script:Items.Count
    Load-CurrentItem
})

$refreshButton.Add_Click({
    try {
        Refresh-Queue
        Rebuild-Categories
        Load-CurrentItem
    } catch {
        [System.Windows.Forms.MessageBox]::Show($_.Exception.Message, "Fehler")
    }
})

$exitButton.Add_Click({
    $form.Close()
})

$approveButton.Add_Click({
    if ($script:Items.Count -eq 0) { return }
    $item = $script:Items[$script:Index]
    $selected = $categoryCombo.SelectedItem
    if (-not $selected) {
        [System.Windows.Forms.MessageBox]::Show("Bitte Kategorie wählen.", "Hinweis")
        return
    }

    $categoryId = $selected.Id
    $categoryName = $selected.Name
    if ($categoryId -eq "__custom__") {
        $categoryName = $customCategoryText.Text.Trim()
        if (-not $categoryName) {
            [System.Windows.Forms.MessageBox]::Show("Bitte neue Kategorie eintragen.", "Hinweis")
            return
        }
        $categoryId = $categoryName
    }

    $approveArgs = New-Object System.Collections.ArrayList
    [void]$approveArgs.Add("--config")
    [void]$approveArgs.Add($ConfigPath)
    [void]$approveArgs.Add("--approve-review")
    [void]$approveArgs.Add([string]$item.id)
    [void]$approveArgs.Add("--json")
    Add-OptionalArg $approveArgs "--review-date" $dateText.Text
    Add-OptionalArg $approveArgs "--review-category-id" $categoryId
    Add-OptionalArg $approveArgs "--review-category-name" $categoryName
    Add-OptionalArg $approveArgs "--review-barcode" $barcodeText.Text
    Add-OptionalArg $approveArgs "--review-archive-code" $archiveCodeText.Text
    Add-OptionalArg $approveArgs "--review-source-type" $sourceTypeCombo.SelectedItem.Id
    Add-OptionalArg $approveArgs "--review-sender" $senderText.Text
    Add-OptionalArg $approveArgs "--review-title" $titleText.Text
    Add-OptionalArg $approveArgs "--review-filename-title" $shortTitleText.Text

    try {
        $json = Invoke-Archive -ArgsList ([string[]]$approveArgs.ToArray())
        $result = $json | ConvertFrom-Json
        [System.Windows.Forms.MessageBox]::Show("Archiviert:`r`n$($result.target_pdf)", "OK")
        Refresh-Queue
        Rebuild-Categories
        Load-CurrentItem
    } catch {
        [System.Windows.Forms.MessageBox]::Show($_.Exception.Message, "Fehler")
    }
})

Rebuild-Categories
Load-CurrentItem

[void][System.Windows.Forms.Application]::Run($form)
