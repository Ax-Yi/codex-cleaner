<#
.SYNOPSIS
Scans for files larger than a threshold and writes a size-sorted CSV report.

.DESCRIPTION
This script only generates a report. It does not delete or modify files.

By default it scans the current user's profile directory. You can pass another
root path, such as C:\Users, if you want to scan all user profiles.

.EXAMPLE
.\Scan-LargeFilesReport.ps1

.EXAMPLE
.\Scan-LargeFilesReport.ps1 -RootPath C:\Users -MinSizeGB 2 -OutputPath .\large-files.csv
#>

[CmdletBinding()]
param(
    [Parameter()]
    [ValidateNotNullOrEmpty()]
    [string]$RootPath = $env:USERPROFILE,

    [Parameter()]
    [ValidateRange(0.01, 1024)]
    [double]$MinSizeGB = 1,

    [Parameter()]
    [ValidateNotNullOrEmpty()]
    [string]$OutputPath = (Join-Path -Path (Get-Location) -ChildPath ("large-files-report-{0}.csv" -f (Get-Date -Format "yyyyMMdd-HHmmss")))
)

$ErrorActionPreference = "Continue"

$resolvedRoot = (Resolve-Path -LiteralPath $RootPath -ErrorAction Stop).Path
$thresholdBytes = [int64]($MinSizeGB * 1GB)

$excludedDirectoryNames = @(
    "Windows",
    "Program Files",
    "Program Files (x86)",
    "AppData",
    "System Volume Information"
)

$excludedFullPaths = @()
foreach ($directoryName in $excludedDirectoryNames) {
    $candidate = Join-Path -Path $env:SystemDrive -ChildPath $directoryName
    if (Test-Path -LiteralPath $candidate -PathType Container) {
        $excludedFullPaths += (Resolve-Path -LiteralPath $candidate).Path.TrimEnd("\")
    }
}

if ($env:USERPROFILE) {
    $appDataPath = Join-Path -Path $env:USERPROFILE -ChildPath "AppData"
    if (Test-Path -LiteralPath $appDataPath -PathType Container) {
        $excludedFullPaths += (Resolve-Path -LiteralPath $appDataPath).Path.TrimEnd("\")
    }
}

function Test-IsExcludedDirectory {
    param(
        [Parameter(Mandatory)]
        [string]$Path
    )

    $normalizedPath = $Path.TrimEnd("\")
    $leafName = Split-Path -Path $normalizedPath -Leaf

    if ($excludedDirectoryNames -contains $leafName) {
        return $true
    }

    foreach ($excludedPath in $excludedFullPaths) {
        if ($normalizedPath.Equals($excludedPath, [System.StringComparison]::OrdinalIgnoreCase) -or
            $normalizedPath.StartsWith($excludedPath + "\", [System.StringComparison]::OrdinalIgnoreCase)) {
            return $true
        }
    }

    return $false
}

$largeFiles = New-Object System.Collections.Generic.List[object]
$pendingDirectories = New-Object System.Collections.Generic.Stack[string]
$skippedDirectories = New-Object System.Collections.Generic.List[string]

if (-not (Test-IsExcludedDirectory -Path $resolvedRoot)) {
    $pendingDirectories.Push($resolvedRoot)
}

while ($pendingDirectories.Count -gt 0) {
    $currentDirectory = $pendingDirectories.Pop()

    try {
        $childItems = Get-ChildItem -LiteralPath $currentDirectory -Force -ErrorAction Stop
    }
    catch {
        $skippedDirectories.Add($currentDirectory)
        Write-Warning ("Skipped inaccessible directory: {0}" -f $currentDirectory)
        continue
    }

    foreach ($item in $childItems) {
        if ($item.PSIsContainer) {
            if (Test-IsExcludedDirectory -Path $item.FullName) {
                continue
            }

            $pendingDirectories.Push($item.FullName)
            continue
        }

        if ($item.Length -ge $thresholdBytes) {
            $largeFiles.Add([PSCustomObject]@{
                SizeGB        = [math]::Round(($item.Length / 1GB), 3)
                SizeBytes     = $item.Length
                LastWriteTime = $item.LastWriteTime
                FullName      = $item.FullName
            })
        }
    }
}

$sortedLargeFiles = $largeFiles | Sort-Object -Property SizeBytes -Descending
$sortedLargeFiles | Export-Csv -LiteralPath $OutputPath -NoTypeInformation -Encoding UTF8

Write-Host ("Report written to: {0}" -f (Resolve-Path -LiteralPath $OutputPath).Path)
Write-Host ("Files >= {0} GB: {1}" -f $MinSizeGB, @($sortedLargeFiles).Count)
Write-Host ("Skipped inaccessible directories: {0}" -f $skippedDirectories.Count)
