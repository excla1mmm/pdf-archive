param(
    [string]$Model = "gemma3:4b",
    [switch]$SkipWingetInstall,
    [switch]$SkipOllamaModel,
    [switch]$AllowNativeArmPython
)

$ErrorActionPreference = "Stop"

$ProjectRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location $ProjectRoot

function Write-Step {
    param([string]$Message)
    Write-Host ""
    Write-Host "== $Message ==" -ForegroundColor Cyan
}

function Write-Ok {
    param([string]$Message)
    Write-Host "[OK] $Message" -ForegroundColor Green
}

function Write-Warn {
    param([string]$Message)
    Write-Host "[WARN] $Message" -ForegroundColor Yellow
}

function Refresh-Path {
    $machinePath = [Environment]::GetEnvironmentVariable("Path", "Machine")
    $userPath = [Environment]::GetEnvironmentVariable("Path", "User")
    $env:Path = "$machinePath;$userPath"
}

function Test-ForeignUserProfilePath {
    param([string]$Path)

    if (-not $Path) {
        return $false
    }

    try {
        $resolved = [System.IO.Path]::GetFullPath($Path)
        $usersRoot = [System.IO.Path]::GetFullPath((Join-Path $env:SystemDrive "Users"))
        $currentProfile = [System.IO.Path]::GetFullPath($env:USERPROFILE)
        $comparison = [System.StringComparison]::OrdinalIgnoreCase

        $underUsers = $resolved.StartsWith("$usersRoot\", $comparison)
        $underCurrentProfile = $resolved.Equals($currentProfile, $comparison) -or $resolved.StartsWith("$currentProfile\", $comparison)
        $underPublicProfile = $resolved.StartsWith("$usersRoot\Public\", $comparison)
        return $underUsers -and (-not $underCurrentProfile) -and (-not $underPublicProfile)
    } catch {
        return $false
    }
}

function Get-UsableCommand {
    param([string]$Name)

    $commands = @(Get-Command $Name -All -ErrorAction SilentlyContinue)
    foreach ($command in $commands) {
        $source = [string]$command.Source
        if (-not $source) {
            continue
        }
        if (Test-ForeignUserProfilePath $source) {
            Write-Warn "Ignoring $Name from another Windows user profile: $source"
            continue
        }
        return $command
    }
    return $null
}

function Test-CommandAvailable {
    param([string]$Name)
    return $null -ne (Get-UsableCommand $Name)
}

function Invoke-Native {
    param(
        [string]$FilePath,
        [string[]]$Arguments
    )
    Write-Host "> $FilePath $($Arguments -join ' ')" -ForegroundColor DarkGray
    & $FilePath @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "$FilePath failed with exit code $LASTEXITCODE."
    }
}

function Invoke-Ollama {
    param([string[]]$Arguments)

    $command = Get-UsableCommand "ollama"
    if (-not $command) {
        return @{
            ExitCode = 1
            Output = "ollama command was not found."
        }
    }

    $previousErrorActionPreference = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        $output = & $command.Source @Arguments 2>&1
        $exitCode = $LASTEXITCODE
        return @{
            ExitCode = $exitCode
            Output = (($output | ForEach-Object { $_.ToString() }) -join "`n")
        }
    } catch {
        return @{
            ExitCode = 1
            Output = $_.Exception.Message
        }
    } finally {
        $ErrorActionPreference = $previousErrorActionPreference
    }
}

function Write-FirstOutputLine {
    param(
        [string]$Prefix,
        [string]$Output
    )

    $line = ([regex]::Split($Output, "\r?\n") | Where-Object { $_.Trim() } | Select-Object -First 1)
    if ($line) {
        Write-Host "$Prefix$line"
    }
}

function Install-WingetPackage {
    param(
        [string]$PackageId,
        [string]$DisplayName,
        [string]$Architecture = ""
    )

    if ($SkipWingetInstall) {
        Write-Warn "Skipping winget install for $DisplayName."
        return $false
    }
    $winget = Get-UsableCommand "winget"
    if (-not $winget) {
        Write-Warn "winget is not available. Install $DisplayName manually."
        return $false
    }

    Write-Step "Installing $DisplayName"
    $wingetArgs = @("install", "--id", $PackageId, "-e", "--silent", "--accept-package-agreements", "--accept-source-agreements")
    if ($Architecture) {
        $wingetArgs += @("--architecture", $Architecture)
    }
    $output = & $winget.Source @wingetArgs 2>&1
    $exitCode = $LASTEXITCODE
    if ($exitCode -ne 0) {
        if ($output) {
            $lines = @($output | ForEach-Object { $_.ToString() } | Where-Object { $_.Trim() } | Select-Object -First 12)
            if ($lines) {
                Write-Warn "winget output:"
                $lines | ForEach-Object { Write-Host "  $_" }
            }
        }
        Write-Warn "winget exit code for $DisplayName was $exitCode."
        Write-Warn "winget could not install $DisplayName. Continue with manual installation if needed."
        Refresh-Path
        return $false
    }

    Refresh-Path
    Write-Ok "$DisplayName installation command completed."
    return $true
}

function Test-HostArm64 {
    return ($env:PROCESSOR_ARCHITECTURE -eq "ARM64") -or ($env:PROCESSOR_ARCHITEW6432 -eq "ARM64")
}

function Get-PythonMachine {
    param([string]$Python)

    try {
        $machine = & $Python -c "import platform; print(platform.machine().lower())" 2>$null
        if ($LASTEXITCODE -eq 0 -and $machine) {
            return ([string]($machine | Select-Object -Last 1)).Trim().ToLowerInvariant()
        }
    } catch {
        return ""
    }
    return ""
}

function Test-PythonSupported {
    param([string]$Python)

    if (Test-ForeignUserProfilePath $Python) {
        Write-Warn "Ignoring Python from another Windows user profile: $Python"
        return $false
    }

    $machine = Get-PythonMachine -Python $Python
    if (-not $machine) {
        Write-Warn "Could not determine Python CPU architecture: $Python"
        return $false
    }

    if ((Test-HostArm64) -and (-not $AllowNativeArmPython) -and ($machine -match "arm")) {
        Write-Warn "Native ARM64 Python found, but this project needs x64 Python on Windows ARM64."
        Write-Warn "Reason: PyMuPDF/zxing-cpp do not reliably provide Windows ARM64 wheels."
        Write-Warn "Python rejected: $Python ($machine)"
        return $false
    }

    Write-Ok "Python architecture accepted: $machine"
    return $true
}

function Test-VenvSupported {
    param([string]$VenvPython)

    if (-not (Test-Path $VenvPython)) {
        return $false
    }

    $venvRoot = Split-Path (Split-Path $VenvPython -Parent) -Parent
    $venvConfig = Join-Path $venvRoot "pyvenv.cfg"
    if (Test-Path $venvConfig) {
        foreach ($line in Get-Content $venvConfig) {
            if ($line -match "^(home|executable)\s*=\s*(.+)$") {
                $basePath = $Matches[2].Trim()
                if (Test-ForeignUserProfilePath $basePath) {
                    Write-Warn "Existing .venv is based on Python from another Windows user profile: $basePath"
                    return $false
                }
            }
        }
    }

    return Test-PythonSupported -Python $VenvPython
}

function Get-PythonExecutable {
    $checks = @(
        @{ File = "py"; Args = @("-3.12-64", "-c", "import sys; print(sys.executable)") },
        @{ File = "py"; Args = @("-3.11-64", "-c", "import sys; print(sys.executable)") },
        @{ File = "py"; Args = @("-3.12", "-c", "import sys; print(sys.executable)") },
        @{ File = "py"; Args = @("-3.11", "-c", "import sys; print(sys.executable)") },
        @{ File = "python"; Args = @("-c", "import sys; print(sys.executable)") },
        @{ File = "python3"; Args = @("-c", "import sys; print(sys.executable)") }
    )

    foreach ($check in $checks) {
        $command = Get-UsableCommand $check.File
        if (-not $command) {
            continue
        }

        try {
            $output = & $command.Source @($check.Args) 2>$null
            if ($LASTEXITCODE -eq 0 -and $output) {
                $candidate = [string]($output | Select-Object -Last 1)
                $candidate = $candidate.Trim()
                if ($candidate -and (Test-Path $candidate) -and (Test-PythonSupported -Python $candidate)) {
                    return $candidate
                }
            }
        } catch {
            continue
        }
    }

    $commonPaths = @(
        "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe",
        "$env:LOCALAPPDATA\Programs\Python\Python311\python.exe",
        "$env:ProgramFiles\Python312\python.exe",
        "$env:ProgramFiles\Python311\python.exe",
        "${env:ProgramFiles(x86)}\Python312\python.exe",
        "${env:ProgramFiles(x86)}\Python311\python.exe"
    )
    foreach ($candidate in $commonPaths) {
        if ($candidate -and (Test-Path $candidate) -and (Test-PythonSupported -Python $candidate)) {
            return $candidate
        }
    }

    return $null
}

function Ensure-Python {
    Write-Step "Checking Python"
    $python = Get-PythonExecutable
    if ($python) {
        Write-Ok "Python found: $python"
        return $python
    }

    if ((Test-HostArm64) -and (-not $AllowNativeArmPython)) {
        Write-Warn "Windows ARM64 detected. Installing x64 Python for binary package compatibility."
        Install-WingetPackage -PackageId "Python.Python.3.12" -DisplayName "Python 3.12 x64" -Architecture "x64" | Out-Null
        $python = Get-PythonExecutable
        if ($python) {
            Write-Ok "Python found: $python"
            return $python
        }

        Write-Warn "Python 3.12 x64 was not detected. Trying Python 3.11 x64."
        Install-WingetPackage -PackageId "Python.Python.3.11" -DisplayName "Python 3.11 x64" -Architecture "x64" | Out-Null
        $python = Get-PythonExecutable
        if ($python) {
            Write-Ok "Python found: $python"
            return $python
        }
    } else {
        Install-WingetPackage -PackageId "Python.Python.3.12" -DisplayName "Python 3.12" | Out-Null
        $python = Get-PythonExecutable
        if ($python) {
            Write-Ok "Python found: $python"
            return $python
        }
    }

    Write-Warn "Python was not found after automatic installation attempt."
    Write-Host "Manual download: https://www.python.org/downloads/windows/"
    if ((Test-HostArm64) -and (-not $AllowNativeArmPython)) {
        Write-Host "Important on Windows ARM64: install the Windows x86-64 executable installer, not the ARM64 installer."
    }
    Write-Host "Important: enable 'Add python.exe to PATH' during installation."
    throw "Install Python 3.11/3.12, reopen PowerShell, then run Install.cmd again."
}

function Add-UserPathIfMissing {
    param([string]$Directory)

    if (-not (Test-Path $Directory)) {
        return
    }

    $userPath = [Environment]::GetEnvironmentVariable("Path", "User")
    $parts = @($userPath -split ";" | Where-Object { $_ })
    if ($parts -notcontains $Directory) {
        [Environment]::SetEnvironmentVariable("Path", (($parts + $Directory) -join ";"), "User")
    }
    Refresh-Path
}

function Get-TesseractExecutable {
    $command = Get-UsableCommand "tesseract"
    if ($command) {
        return [string]$command.Source
    }

    $candidates = @(
        "C:\Program Files\Tesseract-OCR\tesseract.exe",
        "C:\Program Files (x86)\Tesseract-OCR\tesseract.exe"
    )
    foreach ($candidate in $candidates) {
        if (Test-Path $candidate) {
            return $candidate
        }
    }
    return ""
}

function Ensure-TesseractLanguage {
    param(
        [string]$TessdataDir,
        [string]$Language
    )

    if (-not $TessdataDir) {
        return $false
    }

    New-Item -ItemType Directory -Force -Path $TessdataDir | Out-Null
    $target = Join-Path $TessdataDir "$Language.traineddata"
    if (Test-Path $target) {
        return $true
    }

    $url = "https://raw.githubusercontent.com/tesseract-ocr/tessdata_fast/main/$Language.traineddata"
    Write-Host "Downloading Tesseract language data: $Language"
    try {
        Invoke-WebRequest -Uri $url -OutFile $target -UseBasicParsing
        return (Test-Path $target)
    } catch {
        Write-Warn "Could not download Tesseract language '$Language': $($_.Exception.Message)"
        Remove-Item -LiteralPath $target -Force -ErrorAction SilentlyContinue
        return $false
    }
}

function Ensure-Tesseract {
    Write-Step "Checking Tesseract OCR"
    $tesseractPath = Get-TesseractExecutable
    if (-not $tesseractPath) {
        $installed = Install-WingetPackage -PackageId "UB-Mannheim.TesseractOCR" -DisplayName "Tesseract OCR"
        if (-not $installed) {
            Write-Warn "Trying alternate winget package id for Tesseract OCR."
            Install-WingetPackage -PackageId "tesseract-ocr.tesseract" -DisplayName "Tesseract OCR" | Out-Null
        }
    }

    Add-UserPathIfMissing "C:\Program Files\Tesseract-OCR"
    Add-UserPathIfMissing "C:\Program Files (x86)\Tesseract-OCR"

    $tesseractPath = Get-TesseractExecutable
    if (-not $tesseractPath) {
        Write-Warn "Tesseract was not found. OCR for scanned PDFs will not work until it is installed."
        Write-Host "Manual installer: https://github.com/UB-Mannheim/tesseract/wiki"
        Write-Host "After installing manually, reopen PowerShell or add the Tesseract folder to PATH."
        return
    }

    $version = (& $tesseractPath --version 2>$null | Select-Object -First 1)
    Write-Ok "Tesseract found: $version"

    $tessdataDir = Join-Path (Split-Path $tesseractPath -Parent) "tessdata"
    Ensure-TesseractLanguage -TessdataDir $tessdataDir -Language "eng" | Out-Null
    Ensure-TesseractLanguage -TessdataDir $tessdataDir -Language "deu" | Out-Null

    $langs = (& $tesseractPath --list-langs 2>$null)
    if (($langs -notcontains "deu") -or ($langs -notcontains "eng")) {
        Write-Warn "Tesseract languages 'deu' and/or 'eng' were not detected. German/English OCR may be incomplete."
        Write-Host "Tessdata folder: $tessdataDir"
        Write-Host "Expected files: deu.traineddata and eng.traineddata"
    } else {
        Write-Ok "Tesseract languages detected: deu, eng"
    }
}

function Ensure-Ollama {
    Write-Step "Checking Ollama"
    if (-not (Test-CommandAvailable "ollama")) {
        Install-WingetPackage -PackageId "Ollama.Ollama" -DisplayName "Ollama" | Out-Null
    }

    if (-not (Test-CommandAvailable "ollama")) {
        Write-Warn "Ollama was not found. LLM classification will not work until it is installed."
        Write-Host "Manual download: https://ollama.com/download/windows"
        return
    }

    $versionResult = Invoke-Ollama -Arguments @("--version")
    if ($versionResult.Output) {
        Write-Ok "Ollama command found."
        Write-FirstOutputLine -Prefix "Ollama: " -Output $versionResult.Output
    } else {
        Write-Ok "Ollama command found."
    }

    if ($SkipOllamaModel) {
        Write-Warn "Skipping Ollama model download."
        return
    }

    Write-Step "Checking Ollama model $Model"
    $listResult = Invoke-Ollama -Arguments @("list")
    if ($listResult.ExitCode -ne 0) {
        Write-Warn "Ollama is installed, but the local service is not responding."
        if ($listResult.Output) {
            Write-FirstOutputLine -Prefix "Ollama output: " -Output $listResult.Output
        }
        Write-Host "Start Ollama once from the Start menu, then run:"
        Write-Host "  ollama pull $Model"
        Write-Host "After that, Start.cmd can be used normally."
        return
    }

    if ($listResult.Output -match [regex]::Escape($Model)) {
        Write-Ok "Ollama model already installed: $Model"
        return
    }

    Write-Host "Downloading model $Model. This can take a while."
    $pullResult = Invoke-Ollama -Arguments @("pull", $Model)
    if ($pullResult.ExitCode -ne 0) {
        Write-Warn "Could not download $Model automatically. Run later: ollama pull $Model"
        if ($pullResult.Output) {
            Write-FirstOutputLine -Prefix "Ollama output: " -Output $pullResult.Output
        }
    } else {
        Write-Ok "Ollama model installed: $Model"
    }
}

function Ensure-Venv {
    param([string]$Python)

    Write-Step "Creating Python virtual environment"
    $venvPython = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
    if ((Test-Path $venvPython) -and (-not (Test-VenvSupported -VenvPython $venvPython))) {
        Write-Warn "Existing .venv uses an unsupported or foreign Python. Recreating .venv."
        Remove-Item -Recurse -Force (Join-Path $ProjectRoot ".venv")
    }

    if (-not (Test-Path $venvPython)) {
        Invoke-Native -FilePath $Python -Arguments @("-m", "venv", ".venv")
    } else {
        Write-Ok "Virtual environment already exists."
    }

    Write-Step "Installing Python dependencies"
    Invoke-Native -FilePath $venvPython -Arguments @("-m", "pip", "install", "--upgrade", "pip")
    Invoke-Native -FilePath $venvPython -Arguments @("-m", "pip", "install", "--only-binary=:all:", "-r", "requirements.txt")
    Write-Ok "Python dependencies installed."
}

function Ensure-Folders {
    Write-Step "Creating project folders"
    New-Item -ItemType Directory -Force -Path (Join-Path $ProjectRoot "Input") | Out-Null
    New-Item -ItemType Directory -Force -Path (Join-Path $ProjectRoot "Archive") | Out-Null
    Write-Ok "Input and Archive folders are ready."
}

Refresh-Path

Write-Host "PDF Archive MVP Windows setup" -ForegroundColor Cyan
Write-Host "Project: $ProjectRoot"

$python = Ensure-Python
Ensure-Venv -Python $python
Ensure-Tesseract
Ensure-Ollama
Ensure-Folders

Write-Host ""
Write-Host "Setup finished." -ForegroundColor Green
Write-Host "Next steps:"
Write-Host "  1. Put PDF files into the Input folder."
Write-Host "  2. Double-click Start.cmd."
