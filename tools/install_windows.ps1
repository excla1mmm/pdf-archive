param(
    [string]$Model = "gemma3:4b",
    [switch]$SkipWingetInstall,
    [switch]$SkipOllamaModel
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

function Test-CommandAvailable {
    param([string]$Name)
    return $null -ne (Get-Command $Name -ErrorAction SilentlyContinue)
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

function Install-WingetPackage {
    param(
        [string]$PackageId,
        [string]$DisplayName
    )

    if ($SkipWingetInstall) {
        Write-Warn "Skipping winget install for $DisplayName."
        return $false
    }
    if (-not (Test-CommandAvailable "winget")) {
        Write-Warn "winget is not available. Install $DisplayName manually."
        return $false
    }

    Write-Step "Installing $DisplayName"
    & winget install --id $PackageId -e --silent --accept-package-agreements --accept-source-agreements
    if ($LASTEXITCODE -ne 0) {
        Write-Warn "winget could not install $DisplayName. Continue with manual installation if needed."
        Refresh-Path
        return $false
    }

    Refresh-Path
    Write-Ok "$DisplayName installation command completed."
    return $true
}

function Get-PythonExecutable {
    $checks = @(
        @{ File = "py"; Args = @("-3.12", "-c", "import sys; print(sys.executable)") },
        @{ File = "py"; Args = @("-3.11", "-c", "import sys; print(sys.executable)") },
        @{ File = "python"; Args = @("-c", "import sys; print(sys.executable)") },
        @{ File = "python3"; Args = @("-c", "import sys; print(sys.executable)") }
    )

    foreach ($check in $checks) {
        if (-not (Test-CommandAvailable $check.File)) {
            continue
        }

        try {
            $output = & $check.File @($check.Args) 2>$null
            if ($LASTEXITCODE -eq 0 -and $output) {
                $candidate = [string]($output | Select-Object -Last 1)
                $candidate = $candidate.Trim()
                if ($candidate -and (Test-Path $candidate)) {
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
        if ($candidate -and (Test-Path $candidate)) {
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

    Install-WingetPackage -PackageId "Python.Python.3.12" -DisplayName "Python 3.12" | Out-Null
    $python = Get-PythonExecutable
    if ($python) {
        Write-Ok "Python found: $python"
        return $python
    }

    Write-Warn "Python was not found after automatic installation attempt."
    Write-Host "Manual download: https://www.python.org/downloads/windows/"
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

function Ensure-Tesseract {
    Write-Step "Checking Tesseract OCR"
    if (-not (Test-CommandAvailable "tesseract")) {
        Install-WingetPackage -PackageId "UB-Mannheim.TesseractOCR" -DisplayName "Tesseract OCR" | Out-Null
    }

    Add-UserPathIfMissing "C:\Program Files\Tesseract-OCR"

    if (-not (Test-CommandAvailable "tesseract")) {
        Write-Warn "Tesseract was not found. OCR for scanned PDFs will not work until it is installed."
        Write-Host "Manual installer: https://github.com/UB-Mannheim/tesseract/wiki"
        return
    }

    $version = (& tesseract --version 2>$null | Select-Object -First 1)
    Write-Ok "Tesseract found: $version"

    $langs = (& tesseract --list-langs 2>$null)
    if (($langs -notcontains "deu") -or ($langs -notcontains "eng")) {
        Write-Warn "Tesseract languages 'deu' and/or 'eng' were not detected. German/English OCR may be incomplete."
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

    try {
        $version = (& ollama --version 2>$null | Select-Object -First 1)
        Write-Ok "Ollama found: $version"
    } catch {
        Write-Ok "Ollama command found."
    }

    if ($SkipOllamaModel) {
        Write-Warn "Skipping Ollama model download."
        return
    }

    Write-Step "Checking Ollama model $Model"
    & ollama list 1>$null 2>$null
    if ($LASTEXITCODE -ne 0) {
        Write-Warn "Ollama is installed, but the local service is not responding."
        Write-Host "Start Ollama once from the Start menu, then run:"
        Write-Host "  ollama pull $Model"
        return
    }

    $installedModel = (& ollama list) | Select-String -SimpleMatch $Model
    if ($installedModel) {
        Write-Ok "Ollama model already installed: $Model"
        return
    }

    Write-Host "Downloading model $Model. This can take a while."
    & ollama pull $Model
    if ($LASTEXITCODE -ne 0) {
        Write-Warn "Could not download $Model automatically. Run later: ollama pull $Model"
    } else {
        Write-Ok "Ollama model installed: $Model"
    }
}

function Ensure-Venv {
    param([string]$Python)

    Write-Step "Creating Python virtual environment"
    $venvPython = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
    if (-not (Test-Path $venvPython)) {
        Invoke-Native -FilePath $Python -Arguments @("-m", "venv", ".venv")
    } else {
        Write-Ok "Virtual environment already exists."
    }

    Write-Step "Installing Python dependencies"
    Invoke-Native -FilePath $venvPython -Arguments @("-m", "pip", "install", "--upgrade", "pip")
    Invoke-Native -FilePath $venvPython -Arguments @("-m", "pip", "install", "-r", "requirements.txt")
    Write-Ok "Python dependencies installed."
}

function Ensure-Folders {
    Write-Step "Creating project folders"
    New-Item -ItemType Directory -Force -Path (Join-Path $ProjectRoot "Input") | Out-Null
    New-Item -ItemType Directory -Force -Path (Join-Path $ProjectRoot "Archive") | Out-Null
    Write-Ok "Input and Archive folders are ready."
}

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
