<#
.SYNOPSIS
Scans the current user's Desktop and Downloads folders for duplicate files.

.DESCRIPTION
Duplicates are detected by matching both file size and SHA256 hash. The script
does not delete or modify scanned files. It writes a single report named
duplicate_report.txt next to this script, and recommends keeping the newest file
in each duplicate group.
#>

[CmdletBinding()]
param(
    [string]$ReportPath
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Resolve-KnownFolderPath {
    param(
        [Parameter(Mandatory = $true)]
        [string]$RegistryName,

        [Parameter(Mandatory = $true)]
        [string]$FallbackPath
    )

    $userShellFolders = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders'
    $shellFolders = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Explorer\Shell Folders'

    foreach ($registryPath in @($userShellFolders, $shellFolders)) {
        try {
            $value = (Get-ItemProperty -Path $registryPath -Name $RegistryName -ErrorAction Stop).$RegistryName
            if ([string]::IsNullOrWhiteSpace($value)) {
                continue
            }

            $expanded = [Environment]::ExpandEnvironmentVariables($value)
            if (Test-Path -LiteralPath $expanded -PathType Container) {
                return (Resolve-Path -LiteralPath $expanded).Path
            }
        }
        catch {
            continue
        }
    }

    $expandedFallback = [Environment]::ExpandEnvironmentVariables($FallbackPath)
    if (Test-Path -LiteralPath $expandedFallback -PathType Container) {
        return (Resolve-Path -LiteralPath $expandedFallback).Path
    }

    return $null
}

function Format-FileSize {
    param(
        [Parameter(Mandatory = $true)]
        [long]$Bytes
    )

    if ($Bytes -ge 1GB) {
        return '{0:N2} GB' -f ($Bytes / 1GB)
    }

    if ($Bytes -ge 1MB) {
        return '{0:N2} MB' -f ($Bytes / 1MB)
    }

    if ($Bytes -ge 1KB) {
        return '{0:N2} KB' -f ($Bytes / 1KB)
    }

    return "$Bytes B"
}

if ([string]::IsNullOrWhiteSpace($ReportPath)) {
    $scriptDirectory = if ([string]::IsNullOrWhiteSpace($PSScriptRoot)) {
        (Get-Location).Path
    }
    else {
        $PSScriptRoot
    }

    $ReportPath = Join-Path -Path $scriptDirectory -ChildPath 'duplicate_report.txt'
}

$downloadsFolderId = '{374DE290-123F-4565-9164-39C4925E467B}'
$scanRoots = @(
    [pscustomobject]@{
        Name = 'Desktop'
        Path = Resolve-KnownFolderPath -RegistryName 'Desktop' -FallbackPath '%USERPROFILE%\Desktop'
    }
    [pscustomobject]@{
        Name = 'Downloads'
        Path = Resolve-KnownFolderPath -RegistryName $downloadsFolderId -FallbackPath '%USERPROFILE%\Downloads'
    }
) | Where-Object { $null -ne $_.Path } | Sort-Object -Property Path -Unique

$reportFullPath = [System.IO.Path]::GetFullPath($ReportPath)
$reportLines = [System.Collections.Generic.List[string]]::new()

$reportLines.Add('Duplicate File Report')
$reportLines.Add(('Generated: {0}' -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss zzz')))
$reportLines.Add('')
$reportLines.Add('Scanned folders:')

if ($scanRoots.Count -eq 0) {
    $reportLines.Add('  No Desktop or Downloads folders were found for the current user.')
    $reportLines | Set-Content -LiteralPath $reportFullPath -Encoding UTF8
    return
}

foreach ($root in $scanRoots) {
    $reportLines.Add(('  - {0}: {1}' -f $root.Name, $root.Path))
}

$reportLines.Add('')

$files = foreach ($root in $scanRoots) {
    Get-ChildItem -LiteralPath $root.Path -File -Recurse -Force -ErrorAction SilentlyContinue |
        Where-Object {
            try {
                [System.IO.Path]::GetFullPath($_.FullName) -ne $reportFullPath
            }
            catch {
                $true
            }
        } |
        Select-Object FullName, Length, LastWriteTime, LastWriteTimeUtc
}

$files = @($files)
$candidateSizeGroups = @(
    $files |
        Group-Object -Property Length |
        Where-Object { $_.Count -gt 1 }
)

$duplicateGroups = [System.Collections.Generic.List[object]]::new()

foreach ($sizeGroup in $candidateSizeGroups) {
    $hashedFiles = foreach ($file in $sizeGroup.Group) {
        try {
            $hash = Get-FileHash -LiteralPath $file.FullName -Algorithm SHA256 -ErrorAction Stop
            [pscustomobject]@{
                FullName = $file.FullName
                Length = [long]$file.Length
                LastWriteTime = $file.LastWriteTime
                LastWriteTimeUtc = $file.LastWriteTimeUtc
                Hash = $hash.Hash
            }
        }
        catch {
            [pscustomobject]@{
                FullName = $file.FullName
                Length = [long]$file.Length
                LastWriteTime = $file.LastWriteTime
                LastWriteTimeUtc = $file.LastWriteTimeUtc
                Hash = $null
                HashError = $_.Exception.Message
            }
        }
    }

    $hashedFiles |
        Where-Object { $null -ne $_.Hash } |
        Group-Object -Property Hash |
        Where-Object { $_.Count -gt 1 } |
        ForEach-Object {
            $duplicateGroups.Add([pscustomobject]@{
                Hash = $_.Name
                Size = [long]$sizeGroup.Name
                Files = @($_.Group)
            })
        }
}

if ($duplicateGroups.Count -eq 0) {
    $reportLines.Add(('Files scanned: {0}' -f $files.Count))
    $reportLines.Add('Duplicate groups found: 0')
    $reportLines.Add('')
    $reportLines.Add('No duplicate files were found by size and SHA256 hash.')
    $reportLines | Set-Content -LiteralPath $reportFullPath -Encoding UTF8
    return
}

$duplicateFileCount = ($duplicateGroups | ForEach-Object { $_.Files.Count } | Measure-Object -Sum).Sum
$recoverableCount = ($duplicateGroups | ForEach-Object { $_.Files.Count - 1 } | Measure-Object -Sum).Sum
$recoverableBytes = ($duplicateGroups | ForEach-Object { ($_.Files.Count - 1) * $_.Size } | Measure-Object -Sum).Sum

$reportLines.Add(('Files scanned: {0}' -f $files.Count))
$reportLines.Add(('Duplicate groups found: {0}' -f $duplicateGroups.Count))
$reportLines.Add(('Duplicate files in groups: {0}' -f $duplicateFileCount))
$reportLines.Add(('Files that could be removed after review: {0}' -f $recoverableCount))
$reportLines.Add(('Potential space savings after review: {0}' -f (Format-FileSize -Bytes $recoverableBytes)))
$reportLines.Add('')
$reportLines.Add('No files were deleted or modified.')
$reportLines.Add('Each group recommends keeping the newest file by LastWriteTime.')
$reportLines.Add('')

$groupNumber = 1
foreach ($group in ($duplicateGroups | Sort-Object -Property Size -Descending)) {
    $filesInGroup = @($group.Files | Sort-Object -Property LastWriteTimeUtc, FullName -Descending)
    $keep = $filesInGroup[0]

    $reportLines.Add(('Group {0}' -f $groupNumber))
    $reportLines.Add(('  Size: {0} ({1} bytes)' -f (Format-FileSize -Bytes $group.Size), $group.Size))
    $reportLines.Add(('  SHA256: {0}' -f $group.Hash))
    $reportLines.Add(('  Recommended keep: {0}' -f $keep.FullName))
    $reportLines.Add(('  Keep modified: {0}' -f ($keep.LastWriteTime.ToString('yyyy-MM-dd HH:mm:ss'))))
    $reportLines.Add('  Files:')

    foreach ($file in $filesInGroup) {
        $marker = if ($file.FullName -eq $keep.FullName) { 'KEEP' } else { 'DUPLICATE' }
        $reportLines.Add(('    [{0}] {1}' -f $marker, $file.FullName))
        $reportLines.Add(('        Modified: {0}' -f ($file.LastWriteTime.ToString('yyyy-MM-dd HH:mm:ss'))))
    }

    $reportLines.Add('')
    $groupNumber++
}

$reportLines | Set-Content -LiteralPath $reportFullPath -Encoding UTF8
