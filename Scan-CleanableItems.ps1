<#
.SYNOPSIS
    Scans common cleanable locations on Windows and writes clean_report.txt.

.DESCRIPTION
    Read-only scanner. It does not delete, move, or modify scanned files.
    Designed for Windows PowerShell 5.1+.
#>

[CmdletBinding()]
param(
    [string]$ReportPath = (Join-Path -Path (Get-Location) -ChildPath "clean_report.txt"),
    [int64]$LargeFileThresholdBytes = 500MB
)

Set-StrictMode -Version 2.0
$ErrorActionPreference = "Continue"

$ReportRows = New-Object System.Collections.Generic.List[object]
$ScannedRoots = New-Object System.Collections.Generic.List[string]
$SkippedRoots = New-Object System.Collections.Generic.List[string]

function ConvertTo-NormalizedPath {
    param([string]$Path)

    if ([string]::IsNullOrWhiteSpace($Path)) {
        return $null
    }

    try {
        return ([System.IO.Path]::GetFullPath($Path)).TrimEnd('\')
    }
    catch {
        return $Path.TrimEnd('\')
    }
}

function Format-FileSize {
    param([Nullable[Int64]]$Bytes)

    if ($null -eq $Bytes) {
        return "N/A"
    }

    if ($Bytes -ge 1GB) {
        return "{0:N2} GB" -f ($Bytes / 1GB)
    }
    if ($Bytes -ge 1MB) {
        return "{0:N2} MB" -f ($Bytes / 1MB)
    }
    if ($Bytes -ge 1KB) {
        return "{0:N2} KB" -f ($Bytes / 1KB)
    }

    return "{0:N0} B" -f $Bytes
}

function Add-ReportRow {
    param(
        [string]$Category,
        [string]$Path,
        [Nullable[Int64]]$SizeBytes,
        [Nullable[DateTime]]$LastWriteTime,
        [string]$Recommendation
    )

    $ReportRows.Add([pscustomobject]@{
        Category       = $Category
        Path           = $Path
        SizeBytes      = $SizeBytes
        Size           = Format-FileSize -Bytes $SizeBytes
        LastWriteTime  = if ($null -eq $LastWriteTime) { "N/A" } else { $LastWriteTime.ToString("yyyy-MM-dd HH:mm:ss") }
        Recommendation = $Recommendation
    }) | Out-Null
}

$SensitiveRoots = @(
    $env:windir,
    (Join-Path $env:windir "System32"),
    ${env:ProgramFiles},
    ${env:ProgramFiles(x86)},
    $env:ProgramData,
    (Join-Path $env:SystemDrive "Recovery"),
    (Join-Path $env:SystemDrive "System Volume Information"),
    (Join-Path $env:USERPROFILE "AppData")
) | Where-Object { -not [string]::IsNullOrWhiteSpace($_) } | ForEach-Object { ConvertTo-NormalizedPath $_ }

function Test-IsSensitivePath {
    param([string]$Path)

    $normalized = ConvertTo-NormalizedPath $Path
    if ($null -eq $normalized) {
        return $true
    }

    foreach ($root in $SensitiveRoots) {
        if ($normalized.Equals($root, [System.StringComparison]::OrdinalIgnoreCase) -or
            $normalized.StartsWith($root + "\", [System.StringComparison]::OrdinalIgnoreCase)) {
            return $true
        }
    }

    return $false
}

function Test-IsReparsePoint {
    param([System.IO.FileSystemInfo]$Item)

    return (($Item.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0)
}

function Get-SafeChildFiles {
    param(
        [string]$Root,
        [switch]$IncludeAllFiles,
        [switch]$AllowSensitiveRoot
    )

    $normalizedRoot = ConvertTo-NormalizedPath $Root
    if ($null -eq $normalizedRoot -or -not (Test-Path -LiteralPath $normalizedRoot)) {
        return
    }

    if (-not $AllowSensitiveRoot -and (Test-IsSensitivePath -Path $normalizedRoot)) {
        $SkippedRoots.Add($normalizedRoot) | Out-Null
        return
    }

    $ScannedRoots.Add($normalizedRoot) | Out-Null
    $stack = New-Object System.Collections.Stack
    $stack.Push($normalizedRoot)

    while ($stack.Count -gt 0) {
        $current = [string]$stack.Pop()

        try {
            $items = Get-ChildItem -LiteralPath $current -Force -ErrorAction Stop
        }
        catch {
            $SkippedRoots.Add($current) | Out-Null
            continue
        }

        foreach ($item in $items) {
            if (Test-IsReparsePoint -Item $item) {
                continue
            }

            if ($item.PSIsContainer) {
                if ($AllowSensitiveRoot -or -not (Test-IsSensitivePath -Path $item.FullName)) {
                    $stack.Push($item.FullName)
                }
                else {
                    $SkippedRoots.Add($item.FullName) | Out-Null
                }
            }
            elseif ($IncludeAllFiles) {
                $item
            }
        }
    }
}

function Scan-DirectoryFiles {
    param(
        [string]$Category,
        [string]$Root,
        [string]$Recommendation
    )

    foreach ($file in Get-SafeChildFiles -Root $Root -IncludeAllFiles) {
        Add-ReportRow -Category $Category -Path $file.FullName -SizeBytes $file.Length -LastWriteTime $file.LastWriteTime -Recommendation $Recommendation
    }
}

function Scan-RecycleBin {
    try {
        $shell = New-Object -ComObject Shell.Application
        $recycleBin = $shell.Namespace(10)
        if ($null -eq $recycleBin) {
            return
        }

        foreach ($item in $recycleBin.Items()) {
            $deletedFrom = $null
            try { $deletedFrom = $item.ExtendedProperty("System.Recycle.DeletedFrom") } catch {}

            $displayPath = if ([string]::IsNullOrWhiteSpace($deletedFrom)) {
                $item.Name
            }
            else {
                Join-Path -Path $deletedFrom -ChildPath $item.Name
            }

            $sizeBytes = $null
            try {
                $sizeBytes = [int64]$item.ExtendedProperty("System.Size")
            }
            catch {}

            $modified = $null
            try {
                $modifiedText = $item.ExtendedProperty("System.DateModified")
                if ($modifiedText) { $modified = [datetime]$modifiedText }
            }
            catch {}

            Add-ReportRow -Category "Recycle Bin" -Path $displayPath -SizeBytes $sizeBytes -LastWriteTime $modified -Recommendation "If you are sure it is no longer needed, empty it from Recycle Bin. Restore and check first if unsure."
        }
    }
    catch {
        Add-ReportRow -Category "Recycle Bin" -Path "Recycle Bin" -SizeBytes $null -LastWriteTime $null -Recommendation "Could not read Recycle Bin: $($_.Exception.Message)"
    }
}

function Scan-BrowserResidue {
    $localAppData = $env:LOCALAPPDATA
    if ([string]::IsNullOrWhiteSpace($localAppData)) {
        return
    }

    $browserTargets = @(
        @{ Name = "Chrome Cache"; Path = Join-Path $localAppData "Google\Chrome\User Data\Default\Cache" },
        @{ Name = "Chrome Code Cache"; Path = Join-Path $localAppData "Google\Chrome\User Data\Default\Code Cache" },
        @{ Name = "Chrome Download Temp"; Path = Join-Path $localAppData "Google\Chrome\User Data\Default\File System" },
        @{ Name = "Edge Cache"; Path = Join-Path $localAppData "Microsoft\Edge\User Data\Default\Cache" },
        @{ Name = "Edge Code Cache"; Path = Join-Path $localAppData "Microsoft\Edge\User Data\Default\Code Cache" },
        @{ Name = "Edge Download Temp"; Path = Join-Path $localAppData "Microsoft\Edge\User Data\Default\File System" },
        @{ Name = "Firefox Cache"; Path = Join-Path $localAppData "Mozilla\Firefox\Profiles" }
    )

    foreach ($target in $browserTargets) {
        if (Test-Path -LiteralPath $target.Path) {
            $ScannedRoots.Add((ConvertTo-NormalizedPath $target.Path)) | Out-Null

            if ($target.Name -eq "Firefox Cache") {
                $cacheRoots = Get-ChildItem -LiteralPath $target.Path -Directory -Force -ErrorAction SilentlyContinue |
                    ForEach-Object { Join-Path $_.FullName "cache2" } |
                    Where-Object { Test-Path -LiteralPath $_ }

                foreach ($cacheRoot in $cacheRoots) {
                    foreach ($file in Get-SafeChildFiles -Root $cacheRoot -IncludeAllFiles -AllowSensitiveRoot) {
                        Add-ReportRow -Category "Browser Residue" -Path $file.FullName -SizeBytes $file.Length -LastWriteTime $file.LastWriteTime -Recommendation "Browser cache or residue. Usually clean through browser settings; close the browser before handling."
                    }
                }
            }
            else {
                foreach ($file in Get-SafeChildFiles -Root $target.Path -IncludeAllFiles -AllowSensitiveRoot) {
                    Add-ReportRow -Category "Browser Residue" -Path $file.FullName -SizeBytes $file.Length -LastWriteTime $file.LastWriteTime -Recommendation "Browser cache or download residue. Usually clean through browser settings; close the browser before handling."
                }
            }
        }
    }
}

function Scan-LargeFiles {
    $candidateRoots = New-Object System.Collections.Generic.List[string]

    $userKnownFolders = @(
        "Desktop",
        "Downloads",
        "Documents",
        "Pictures",
        "Videos",
        "Music"
    )

    foreach ($folderName in $userKnownFolders) {
        $path = Join-Path $env:USERPROFILE $folderName
        if (Test-Path -LiteralPath $path) {
            $candidateRoots.Add($path) | Out-Null
        }
    }

    try {
        $drives = Get-PSDrive -PSProvider FileSystem -ErrorAction Stop | Where-Object { $_.Root -match "^[A-Z]:\\$" }
        foreach ($drive in $drives) {
            $rootItems = Get-ChildItem -LiteralPath $drive.Root -Directory -Force -ErrorAction SilentlyContinue
            foreach ($item in $rootItems) {
                if (-not (Test-IsSensitivePath -Path $item.FullName) -and -not (Test-IsReparsePoint -Item $item)) {
                    $candidateRoots.Add($item.FullName) | Out-Null
                }
            }
        }
    }
    catch {}

    $uniqueRoots = $candidateRoots |
        ForEach-Object { ConvertTo-NormalizedPath $_ } |
        Where-Object { $_ -and -not (Test-IsSensitivePath -Path $_) } |
        Sort-Object -Unique

    foreach ($root in $uniqueRoots) {
        foreach ($file in Get-SafeChildFiles -Root $root -IncludeAllFiles) {
            if ($file.Length -ge $LargeFileThresholdBytes) {
                Add-ReportRow -Category "Large File" -Path $file.FullName -SizeBytes $file.Length -LastWriteTime $file.LastWriteTime -Recommendation "Larger than 500 MB. Confirm its purpose, then move to external/cloud storage or manually delete unneeded copies."
            }
        }
    }
}

function Write-CleanReport {
    $now = Get-Date
    $totalBytes = ($ReportRows | Where-Object { $null -ne $_.SizeBytes } | Measure-Object -Property SizeBytes -Sum).Sum
    if ($null -eq $totalBytes) { $totalBytes = 0 }

    $lines = New-Object System.Collections.Generic.List[string]
    $lines.Add("Windows Cleanable Items Scan Report") | Out-Null
    $lines.Add(("Generated at: {0}" -f $now.ToString("yyyy-MM-dd HH:mm:ss"))) | Out-Null
    $lines.Add("Scan mode: read-only; no files are deleted, moved, or modified") | Out-Null
    $lines.Add(("Large file threshold: {0}" -f (Format-FileSize -Bytes $LargeFileThresholdBytes))) | Out-Null
    $lines.Add(("Items found: {0}" -f $ReportRows.Count)) | Out-Null
    $lines.Add(("Estimated total size to review: {0}" -f (Format-FileSize -Bytes $totalBytes))) | Out-Null
    $lines.Add("") | Out-Null
    $lines.Add("Scanned locations:") | Out-Null

    foreach ($root in ($ScannedRoots | Sort-Object -Unique)) {
        $lines.Add(("  - {0}" -f $root)) | Out-Null
    }

    $lines.Add("") | Out-Null
    $lines.Add("Skipped/protected locations:") | Out-Null
    foreach ($root in (($SensitiveRoots + $SkippedRoots) | Where-Object { $_ } | Sort-Object -Unique)) {
        $lines.Add(("  - {0}" -f $root)) | Out-Null
    }

    $lines.Add("") | Out-Null
    $lines.Add("Details:") | Out-Null
    $lines.Add("--------------------------------------------------------------------------------") | Out-Null

    $sortedRows = $ReportRows | Sort-Object Category, @{ Expression = "SizeBytes"; Descending = $true }, Path
    foreach ($row in $sortedRows) {
        $lines.Add(("Category: {0}" -f $row.Category)) | Out-Null
        $lines.Add(("Path: {0}" -f $row.Path)) | Out-Null
        $lines.Add(("Size: {0}" -f $row.Size)) | Out-Null
        $lines.Add(("Last modified: {0}" -f $row.LastWriteTime)) | Out-Null
        $lines.Add(("Recommended action: {0}" -f $row.Recommendation)) | Out-Null
        $lines.Add("--------------------------------------------------------------------------------") | Out-Null
    }

    if ($ReportRows.Count -eq 0) {
        $lines.Add("No matching items were found.") | Out-Null
    }

    Set-Content -LiteralPath $ReportPath -Value $lines -Encoding UTF8
}

$downloads = Join-Path $env:USERPROFILE "Downloads"
$desktop = Join-Path $env:USERPROFILE "Desktop"
$tempRoots = @($env:TEMP, $env:TMP, (Join-Path $env:windir "Temp")) | Sort-Object -Unique

Scan-DirectoryFiles -Category "Downloads" -Root $downloads -Recommendation "Downloads folder item. Confirm the purpose, then archive, move, or manually delete if no longer needed."
Scan-DirectoryFiles -Category "Desktop" -Root $desktop -Recommendation "Desktop item. Keep active files; archive or manually delete old/unneeded items."

foreach ($tempRoot in $tempRoots) {
    if (-not [string]::IsNullOrWhiteSpace($tempRoot)) {
        if ((ConvertTo-NormalizedPath $tempRoot) -ieq (ConvertTo-NormalizedPath (Join-Path $env:windir "Temp"))) {
            $ScannedRoots.Add((ConvertTo-NormalizedPath $tempRoot)) | Out-Null
            foreach ($file in Get-ChildItem -LiteralPath $tempRoot -File -Force -ErrorAction SilentlyContinue) {
                Add-ReportRow -Category "Temporary Files" -Path $file.FullName -SizeBytes $file.Length -LastWriteTime $file.LastWriteTime -Recommendation "System temporary file. Prefer Windows Disk Cleanup or Storage Sense."
            }
        }
        else {
            Scan-DirectoryFiles -Category "Temporary Files" -Root $tempRoot -Recommendation "User temporary file. Usually safe to clean after closing running applications."
        }
    }
}

Scan-RecycleBin
Scan-BrowserResidue
Scan-LargeFiles
Write-CleanReport

Write-Host ("Scan complete. Report generated: {0}" -f (ConvertTo-NormalizedPath $ReportPath))
