param(
    [string]$RootPath = (Get-Location).Path,
    [string]$ReportPath = (Join-Path (Get-Location).Path "privacy_scan_report.txt"),
    [int]$MaxFileSizeMB = 25,
    [string[]]$ExcludeDirs = @(".git", "node_modules", "vendor", "dist", "build", ".next", ".nuxt", "coverage")
)

$keywords = @(
    "cookie",
    "cookies",
    "token",
    "api_key",
    "apikey",
    "secret",
    "password",
    "passwd",
    ".env",
    "config.json",
    "headers",
    "authorization"
)

$root = (Resolve-Path -LiteralPath $RootPath).Path
$reportFullPath = [System.IO.Path]::GetFullPath($ReportPath)
$scriptFullPath = if ($PSCommandPath) { [System.IO.Path]::GetFullPath($PSCommandPath) } else { $null }
$maxBytes = [int64]$MaxFileSizeMB * 1MB
$keywordRegexes = @{}

foreach ($keyword in $keywords) {
    $keywordRegexes[$keyword] = [regex]::new([regex]::Escape($keyword), [System.Text.RegularExpressions.RegexOptions]::IgnoreCase)
}

function Test-IsExcludedPath {
    param(
        [string]$Path,
        [string]$Root,
        [string[]]$ExcludedNames
    )

    $relative = $Path.Substring($Root.Length).TrimStart("\", "/")
    if ([string]::IsNullOrWhiteSpace($relative)) {
        return $false
    }

    $parts = $relative -split "[\\/]+"
    foreach ($part in $parts) {
        if ($ExcludedNames -contains $part) {
            return $true
        }
    }

    return $false
}

$findings = New-Object System.Collections.Generic.List[object]
$skipped = New-Object System.Collections.Generic.List[object]
$errors = New-Object System.Collections.Generic.List[object]

$files = Get-ChildItem -LiteralPath $root -Recurse -File -Force -ErrorAction SilentlyContinue |
    Where-Object {
        -not (Test-IsExcludedPath -Path $_.FullName -Root $root -ExcludedNames $ExcludeDirs) -and
        ([System.IO.Path]::GetFullPath($_.FullName) -ne $reportFullPath) -and
        ($null -eq $scriptFullPath -or [System.IO.Path]::GetFullPath($_.FullName) -ne $scriptFullPath)
    }

foreach ($file in $files) {
    $fileHits = New-Object System.Collections.Generic.HashSet[string]
    $contentHits = New-Object System.Collections.Generic.HashSet[string]

    foreach ($keyword in $keywords) {
        if ($keywordRegexes[$keyword].IsMatch($file.Name)) {
            [void]$fileHits.Add($keyword)
        }
    }

    if ($file.Length -gt $maxBytes) {
        $skipped.Add([pscustomobject]@{
            Path = $file.FullName
            Reason = "Skipped content scan because file is larger than $MaxFileSizeMB MB"
        }) | Out-Null
    }
    else {
        try {
            $content = Get-Content -LiteralPath $file.FullName -Raw -ErrorAction Stop
            foreach ($keyword in $keywords) {
                if ($keywordRegexes[$keyword].IsMatch($content)) {
                    [void]$contentHits.Add($keyword)
                }
            }
        }
        catch {
            $errors.Add([pscustomobject]@{
                Path = $file.FullName
                Error = $_.Exception.Message
            }) | Out-Null
        }
    }

    if ($fileHits.Count -gt 0) {
        $findings.Add([pscustomobject]@{
            Path = $file.FullName
            MatchType = "FileName"
            Keywords = (($fileHits | Sort-Object) -join ", ")
        }) | Out-Null
    }

    if ($contentHits.Count -gt 0) {
        $findings.Add([pscustomobject]@{
            Path = $file.FullName
            MatchType = "Content"
            Keywords = (($contentHits | Sort-Object) -join ", ")
        }) | Out-Null
    }
}

$report = New-Object System.Collections.Generic.List[string]
$report.Add("Privacy scan report") | Out-Null
$report.Add(("Generated: {0}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss zzz"))) | Out-Null
$report.Add(("RootPath: {0}" -f $root)) | Out-Null
$report.Add("Mode: Local-only scan. No files uploaded. No files deleted. Secret values and matching lines are not printed.") | Out-Null
$report.Add(("Keywords: {0}" -f ($keywords -join ", "))) | Out-Null
$report.Add(("Excluded directories: {0}" -f ($ExcludeDirs -join ", "))) | Out-Null
$report.Add(("Max content scan size per file: {0} MB" -f $MaxFileSizeMB)) | Out-Null
$report.Add("") | Out-Null
$report.Add(("Files scanned: {0}" -f @($files).Count)) | Out-Null
$report.Add(("Findings: {0}" -f $findings.Count)) | Out-Null
$report.Add(("Skipped content scans: {0}" -f $skipped.Count)) | Out-Null
$report.Add(("Read errors: {0}" -f $errors.Count)) | Out-Null
$report.Add("") | Out-Null

if ($findings.Count -gt 0) {
    $report.Add("Findings") | Out-Null
    foreach ($finding in ($findings | Sort-Object Path, MatchType)) {
        $report.Add(("- Path: {0}" -f $finding.Path)) | Out-Null
        $report.Add(("  MatchType: {0}" -f $finding.MatchType)) | Out-Null
        $report.Add(("  Keywords: {0}" -f $finding.Keywords)) | Out-Null
    }
}
else {
    $report.Add("Findings: none") | Out-Null
}

if ($skipped.Count -gt 0) {
    $report.Add("") | Out-Null
    $report.Add("Skipped") | Out-Null
    foreach ($item in ($skipped | Sort-Object Path)) {
        $report.Add(("- Path: {0}" -f $item.Path)) | Out-Null
        $report.Add(("  Reason: {0}" -f $item.Reason)) | Out-Null
    }
}

if ($errors.Count -gt 0) {
    $report.Add("") | Out-Null
    $report.Add("Read errors") | Out-Null
    foreach ($item in ($errors | Sort-Object Path)) {
        $report.Add(("- Path: {0}" -f $item.Path)) | Out-Null
        $report.Add(("  Error: {0}" -f $item.Error)) | Out-Null
    }
}

$report | Set-Content -LiteralPath $ReportPath -Encoding UTF8
Write-Host ("Report written to: {0}" -f (Resolve-Path -LiteralPath $ReportPath).Path)
