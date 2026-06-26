param(
    [string]$Config = "config.example.yml",
    [string]$Python = "python"
)

$ErrorActionPreference = "Stop"

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

    $output = & $Python $ArchiveScript @ArgsList
    if ($LASTEXITCODE -ne 0) {
        throw "archive_pdf.py failed with exit code $LASTEXITCODE."
    }
    return ($output -join "`r`n")
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

function Set-Form-Enabled {
    param([bool]$Enabled)

    $dateText.Enabled = $Enabled
    $barcodeText.Enabled = $Enabled
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
$form.Size = New-Object System.Drawing.Size(820, 620)
$form.MinimumSize = New-Object System.Drawing.Size(760, 560)

$fileLabel = Add-Label $form "Datei:" 14 14 600
$countLabel = Add-Label $form "" 690 14 90

Add-Label $form "Datum (YYYY-MM-DD)" 14 52 150 | Out-Null
$dateText = Add-TextBox $form 180 50 160

Add-Label $form "Barcode" 14 84 150 | Out-Null
$barcodeText = Add-TextBox $form 180 82 420

Add-Label $form "Kategorie" 14 116 150 | Out-Null
$categoryCombo = New-Object System.Windows.Forms.ComboBox
$categoryCombo.Location = New-Object System.Drawing.Point(180, 114)
$categoryCombo.Size = New-Object System.Drawing.Size(420, 24)
$categoryCombo.DropDownStyle = "DropDownList"
$form.Controls.Add($categoryCombo)

Add-Label $form "Neue Kategorie" 14 148 150 | Out-Null
$customCategoryText = Add-TextBox $form 180 146 420

Add-Label $form "Absender" 14 180 150 | Out-Null
$senderText = Add-TextBox $form 180 178 420

Add-Label $form "Titel" 14 212 150 | Out-Null
$titleText = Add-TextBox $form 180 210 420

Add-Label $form "Dateiname-Kurztext" 14 244 150 | Out-Null
$shortTitleText = Add-TextBox $form 180 242 420

Add-Label $form "Review-Gründe" 14 282 150 | Out-Null
$reasonText = New-Object System.Windows.Forms.TextBox
$reasonText.Location = New-Object System.Drawing.Point(180, 280)
$reasonText.Size = New-Object System.Drawing.Size(580, 48)
$reasonText.Multiline = $true
$reasonText.ReadOnly = $true
$form.Controls.Add($reasonText)

Add-Label $form "Textauszug" 14 344 150 | Out-Null
$excerptText = New-Object System.Windows.Forms.TextBox
$excerptText.Location = New-Object System.Drawing.Point(180, 342)
$excerptText.Size = New-Object System.Drawing.Size(580, 120)
$excerptText.Multiline = $true
$excerptText.ScrollBars = "Vertical"
$excerptText.ReadOnly = $true
$form.Controls.Add($excerptText)

$openButton = New-Object System.Windows.Forms.Button
$openButton.Text = "PDF öffnen"
$openButton.Location = New-Object System.Drawing.Point(180, 490)
$openButton.Size = New-Object System.Drawing.Size(105, 30)
$form.Controls.Add($openButton)

$skipButton = New-Object System.Windows.Forms.Button
$skipButton.Text = "Weiter"
$skipButton.Location = New-Object System.Drawing.Point(295, 490)
$skipButton.Size = New-Object System.Drawing.Size(90, 30)
$form.Controls.Add($skipButton)

$approveButton = New-Object System.Windows.Forms.Button
$approveButton.Text = "Übernehmen"
$approveButton.Location = New-Object System.Drawing.Point(395, 490)
$approveButton.Size = New-Object System.Drawing.Size(115, 30)
$form.Controls.Add($approveButton)

$refreshButton = New-Object System.Windows.Forms.Button
$refreshButton.Text = "Aktualisieren"
$refreshButton.Location = New-Object System.Drawing.Point(520, 490)
$refreshButton.Size = New-Object System.Drawing.Size(110, 30)
$form.Controls.Add($refreshButton)

$exitButton = New-Object System.Windows.Forms.Button
$exitButton.Text = "Beenden"
$exitButton.Location = New-Object System.Drawing.Point(640, 490)
$exitButton.Size = New-Object System.Drawing.Size(90, 30)
$form.Controls.Add($exitButton)

$categoryCombo.Add_SelectedIndexChanged({
    $selected = $categoryCombo.SelectedItem
    $customCategoryText.Enabled = ($selected -and $selected.Id -eq "__custom__")
})

$openButton.Add_Click({
    if ($script:Items.Count -eq 0) { return }
    Start-Process -FilePath $script:Items[$script:Index].pdf_path
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

    $args = @(
        "--config", $ConfigPath,
        "--approve-review", $item.id,
        "--json",
        "--review-date", $dateText.Text.Trim(),
        "--review-category-id", $categoryId,
        "--review-category-name", $categoryName,
        "--review-barcode", $barcodeText.Text.Trim(),
        "--review-sender", $senderText.Text.Trim(),
        "--review-title", $titleText.Text.Trim(),
        "--review-filename-title", $shortTitleText.Text.Trim()
    )

    try {
        $json = Invoke-Archive $args
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
