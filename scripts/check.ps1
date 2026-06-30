$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

function Invoke-Check {
    param (
        [Parameter(Mandatory = $true)]
        [string] $Name,

        [Parameter(Mandatory = $true)]
        [string[]] $Command
    )

    Write-Host "==> $Name"
    & $Command[0] $Command[1..($Command.Length - 1)]

    if ($LASTEXITCODE -ne 0) {
        throw "$Name failed with exit code $LASTEXITCODE"
    }
}

Invoke-Check "ruff format" @("uv", "run", "ruff", "format", "--check", ".")
Invoke-Check "ruff check" @("uv", "run", "ruff", "check", ".")
Invoke-Check "ty check" @("uv", "run", "ty", "check")
Invoke-Check "pytest" @("uv", "run", "pytest")
