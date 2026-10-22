# Windows PowerShell 5.1. No target executable or DLL is executed by this module.
Set-StrictMode -Version 2.0
$ErrorActionPreference = 'Stop'
$script:Product = 'cascadeur MMD toolkit'
$script:Release = '1.0'
$script:LegacyRuntimeTargets = @(
    'resources/scripts/python/scripts/vmd_bridge/native/qt_list_ref.dll',
    'python3.dll',
    'python/Lib/site-packages/PySide6/__init__.py',
    'python/Lib/site-packages/PySide6/_config.py',
    'python/Lib/site-packages/PySide6/QtCore.pyd',
    'python/Lib/site-packages/PySide6/QtCore.pyi',
    'python/Lib/site-packages/PySide6/QtNetwork.pyd',
    'python/Lib/site-packages/PySide6/QtNetwork.pyi',
    'python/Lib/site-packages/PySide6/QtQml.pyd',
    'python/Lib/site-packages/PySide6/QtQml.pyi',
    'python/Lib/site-packages/PySide6/pyside6.abi3.dll',
    'python/Lib/site-packages/PySide6/pyside6qml.abi3.dll',
    'python/Lib/site-packages/PySide6/support/__init__.py',
    'python/Lib/site-packages/PySide6/support/deprecated.py',
    'python/Lib/site-packages/shiboken6/__init__.py',
    'python/Lib/site-packages/shiboken6/_config.py',
    'python/Lib/site-packages/shiboken6/Shiboken.pyd',
    'python/Lib/site-packages/shiboken6/shiboken6.abi3.dll'
)

function Get-ToolkitHash([string]$Path) {
    $algorithm=[Security.Cryptography.SHA256]::Create()
    $stream=[IO.File]::OpenRead($Path)
    try { return [BitConverter]::ToString($algorithm.ComputeHash($stream)).Replace('-','') }
    finally { $stream.Dispose(); $algorithm.Dispose() }
}
function Write-ToolkitJson([object]$Value, [string]$Path) {
    $text = $Value | ConvertTo-Json -Depth 30
    $temporary=$Path+'.'+[Guid]::NewGuid().ToString('N')+'.tmp'
    try {
        [IO.File]::WriteAllText($temporary, $text, (New-Object Text.UTF8Encoding($true)))
        if (Test-Path -LiteralPath $Path -PathType Leaf) { [IO.File]::Replace($temporary,$Path,[NullString]::Value) }
        else { [IO.File]::Move($temporary,$Path) }
    } finally { if(Test-Path -LiteralPath $temporary -PathType Leaf){[IO.File]::Delete($temporary)} }
}
function Assert-ToolkitNoReparse([string]$Path) {
    $cursor = [IO.Path]::GetFullPath($Path)
    while ($cursor) {
        if (Test-Path -LiteralPath $cursor) {
            $item = Get-Item -LiteralPath $cursor -Force
            if ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) { throw "Reparse point is not allowed: $cursor" }
        }
        $parent = [IO.Directory]::GetParent($cursor)
        if ($null -eq $parent) { break }
        $cursor = $parent.FullName
    }
}
function Get-ToolkitSafePath([string]$Root, [string]$Relative) {
    if ([string]::IsNullOrWhiteSpace($Relative) -or $Relative.Contains('\') -or $Relative.StartsWith('/') -or $Relative.Contains(':')) {
        throw "Invalid relative path: $Relative"
    }
    foreach ($segment in $Relative.Split('/')) {
        if (!$segment -or $segment -eq '.' -or $segment -eq '..' -or $segment.EndsWith('.') -or $segment.EndsWith(' ') -or
            $segment.IndexOfAny([IO.Path]::GetInvalidFileNameChars()) -ge 0 -or $segment -match '^(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(\.|$)') {
            throw "Invalid path segment: $Relative"
        }
    }
    $base = [IO.Path]::GetFullPath($Root).TrimEnd('\')
    $full = [IO.Path]::GetFullPath((Join-Path $base ($Relative.Replace('/','\'))))
    if (!$full.StartsWith($base + '\', [StringComparison]::OrdinalIgnoreCase)) { throw "Path leaves root: $Relative" }
    Assert-ToolkitNoReparse $full
    return $full
}
function Assert-ToolkitTarget([string]$Relative) {
    if ($Relative -cin $script:LegacyRuntimeTargets) { return }
    if ($Relative -eq 'D3D11.dll' -or
        $Relative.StartsWith('resources/scripts/python/scripts/vmd_bridge/', [StringComparison]::Ordinal) -or
        $Relative.StartsWith('resources/scripts/python/commands/mmd_toolkit/', [StringComparison]::Ordinal) -or
        $Relative -eq 'resources/scripts/python/events/scene_activated/vmd_menu_inject.py') { return }
    throw "Target is outside the toolkit runtime: $Relative"
}
function Get-ToolkitRoot([string]$Path) {
    $drivePath=$Path -match '^[A-Za-z]:[\\/]'
    $uncPath=$Path -match '^\\\\[^\\/:?]+\\[^\\/:?]+(\\|$)'
    if (!$Path -or ![IO.Path]::IsPathRooted($Path) -or (!$drivePath -and !$uncPath)) { throw 'Choose an absolute Cascadeur installation directory.' }
    $full = [IO.Path]::GetFullPath($Path).TrimEnd('\')
    if ($full -eq [IO.Path]::GetPathRoot($full).TrimEnd('\')) { throw 'A drive root is not a Cascadeur installation directory.' }
    Assert-ToolkitNoReparse $full
    if (!(Test-Path -LiteralPath $full -PathType Container)) { throw "Installation directory not found: $full" }
    return $full
}
function Get-ToolkitPe([string]$Path) {
    # Parse PE headers and export names without LoadLibrary or executing target code.
    $bytes = [IO.File]::ReadAllBytes($Path)
    if ($bytes.Length -lt 256 -or $bytes[0] -ne 77 -or $bytes[1] -ne 90) { throw "Not a PE image: $Path" }
    $pe = [BitConverter]::ToInt32($bytes, 60)
    if ($pe -lt 64 -or $pe + 264 -gt $bytes.Length -or [BitConverter]::ToUInt32($bytes,$pe) -ne 17744) { throw "Invalid PE header: $Path" }
    $machine = [BitConverter]::ToUInt16($bytes,$pe+4)
    $sections = [BitConverter]::ToUInt16($bytes,$pe+6)
    $optSize = [BitConverter]::ToUInt16($bytes,$pe+20)
    $opt = $pe+24
    if ([BitConverter]::ToUInt16($bytes,$opt) -ne 523 -or $optSize -lt 120) { throw "64-bit PE32+ is required: $Path" }
    $table = $opt+$optSize
    if ($sections -gt 96 -or $table+$sections*40 -gt $bytes.Length) { throw "Invalid PE sections: $Path" }
    $sectionRows = @()
    for ($i=0; $i -lt $sections; $i++) {
        $at = $table+$i*40
        $sectionRows += ,@([BitConverter]::ToUInt32($bytes,$at+12), [Math]::Max([BitConverter]::ToUInt32($bytes,$at+8),[BitConverter]::ToUInt32($bytes,$at+16)), [BitConverter]::ToUInt32($bytes,$at+20))
    }
    $rvaOffset = {
        param([uint32]$Rva)
        foreach ($s in $sectionRows) {
            if ($Rva -ge $s[0] -and [uint64]$Rva -lt [uint64]$s[0]+$s[1]) {
                $offset = [int64]$s[2]+$Rva-$s[0]
                if ($offset -lt 0 -or $offset -ge $bytes.Length) { throw 'PE RVA outside file.' }
                return [int]$offset
            }
        }
        if ($Rva -lt [BitConverter]::ToUInt32($bytes,$opt+60) -and $Rva -lt $bytes.Length) { return [int]$Rva }
        throw 'PE RVA has no backing section.'
    }
    $names = New-Object 'Collections.Generic.HashSet[string]' ([StringComparer]::Ordinal)
    $exportRva = [BitConverter]::ToUInt32($bytes,$opt+112)
    if ($exportRva) {
        $ex = & $rvaOffset $exportRva
        if ($ex+40 -gt $bytes.Length) { throw 'Truncated PE export directory.' }
        $count = [BitConverter]::ToUInt32($bytes,$ex+24)
        if ($count -gt 1000000) { throw 'Invalid PE export count.' }
        $nameTable = & $rvaOffset ([BitConverter]::ToUInt32($bytes,$ex+32))
        if ([uint64]$nameTable+[uint64]$count*4 -gt $bytes.Length) { throw 'Truncated PE name table.' }
        for ($i=0; $i -lt $count; $i++) {
            $start = & $rvaOffset ([BitConverter]::ToUInt32($bytes,$nameTable+$i*4))
            $end = $start
            while ($end -lt $bytes.Length -and $bytes[$end] -ne 0 -and $end-$start -lt 4096) { $end++ }
            if ($end -eq $bytes.Length -or $end-$start -eq 4096) { throw 'Invalid PE export name.' }
            [void]$names.Add([Text.Encoding]::ASCII.GetString($bytes,$start,$end-$start))
        }
    }
    [pscustomobject]@{ Machine=$machine; Exports=$names }
}
function Assert-ToolkitCapabilities([string]$Root, [object]$Requirements) {
    foreach ($native in $Requirements.native) {
        $path = Get-ToolkitSafePath $Root $native.path
        if (!(Test-Path -LiteralPath $path -PathType Leaf)) { throw "Missing host capability: $($native.path)" }
        $pe = Get-ToolkitPe $path
        if ($pe.Machine -ne $Requirements.machine) { throw "Unsupported architecture: $($native.path). Windows x64 is required." }
        foreach ($symbol in $native.exports) {
            if (!$pe.Exports.Contains([string]$symbol)) { throw "Missing native capability $symbol in $($native.path)" }
        }
    }
    foreach ($relative in $Requirements.files) {
        if (!(Test-Path -LiteralPath (Get-ToolkitSafePath $Root $relative) -PathType Leaf)) { throw "Missing Python scripting capability: $relative" }
    }
    foreach ($relative in $Requirements.directories) {
        if (!(Test-Path -LiteralPath (Get-ToolkitSafePath $Root $relative) -PathType Container)) { throw "Missing official scripting directory: $relative" }
    }
}
function Get-ToolkitHostVersion([string]$Path) {
    return [Diagnostics.FileVersionInfo]::GetVersionInfo($Path)
}
function Get-ToolkitHostRelease([string]$Root) {
    $exe=Get-ToolkitSafePath $Root 'cascadeur.exe'
    if (!(Test-Path -LiteralPath $exe -PathType Leaf)) { throw 'Missing host capability: cascadeur.exe' }
    $info=Get-ToolkitHostVersion $exe
    $match=[regex]::Match([string]$info.FileVersion, '^(\d{4})\.(\d+)\.(\d+)(?:\.|$)')
    if (!$match.Success) { throw 'Cannot identify the Cascadeur release from cascadeur.exe VERSIONINFO.' }
    return [version]($match.Groups[1].Value+'.'+$match.Groups[2].Value+'.'+$match.Groups[3].Value)
}
function Test-ToolkitCacheOnlyDirectory([string]$Root, [string]$Folder, [object[]]$Files) {
    # Restore preserves unlisted generated files. Permit only empty directories
    # and recognized CPython 3.11 cache names; never erase or accept foreign code.
    $allowedDirectories=New-Object 'Collections.Generic.HashSet[string]' ([StringComparer]::Ordinal)
    $patterns=New-Object 'Collections.Generic.List[string]'
    foreach ($file in $Files) {
        $local=$file.target.Substring($Folder.Length+1)
        $separator=$local.LastIndexOf('/')
        $parent=$(if($separator -ge 0){$local.Substring(0,$separator)}else{''})
        if ($parent) { [void]$allowedDirectories.Add($parent) }
        if ($local.EndsWith('.py',[StringComparison]::Ordinal)) {
            $cache=$(if($parent){$parent+'/__pycache__'}else{'__pycache__'})
            [void]$allowedDirectories.Add($cache)
            $filename=$local.Substring($separator+1)
            $stem=$filename.Substring(0,$filename.Length-3)
            $patterns.Add('^'+[regex]::Escape($cache+'/'+$stem)+'\.cpython-311(?:\.opt-[12])?\.pyc$')
        }
    }
    $directory=Get-ToolkitSafePath $Root $Folder
    foreach ($item in Get-ChildItem -LiteralPath $directory -Recurse -Force) {
        Assert-ToolkitNoReparse $item.FullName
        $local=$item.FullName.Substring($directory.Length+1).Replace('\','/')
        if ($item.PSIsContainer) {
            if (!$allowedDirectories.Contains($local)) { return $false }
        } else {
            $known=$false
            foreach ($pattern in $patterns) { if ($local -cmatch $pattern) { $known=$true; break } }
            if (!$known) { return $false }
        }
    }
    return $true
}
function Get-ToolkitHostProfile([string]$Root, [object]$Manifest) {
    $hostRelease=Get-ToolkitHostRelease $Root
    if ($hostRelease -lt [version]'2026.1.3') { throw 'Cascadeur 2026.1.3 or later is required.' }
    if ($hostRelease -ge [version]'2026.2.0') {
        Assert-ToolkitCapabilities $Root $Manifest.requirements
        return 'native'
    }
    if (Test-Path -LiteralPath (Get-ToolkitSafePath $Root 'resources/scripts/python/python_actions_rule.py')) {
        throw 'Cascadeur 2026.1 has mixed scripting rules. Use a clean host installation before installing the toolkit.'
    }
    Assert-ToolkitCapabilities $Root $Manifest.legacy_requirements
    foreach ($dll in @('Qt6Core.dll','Qt6Gui.dll','Qt6Network.dll','Qt6Qml.dll','Qt6Quick.dll')) {
        $version = Get-ToolkitHostVersion (Get-ToolkitSafePath $Root $dll)
        if ($version.FileMajorPart -ne 6 -or $version.FileMinorPart -ne 5 -or $version.FileBuildPart -ne 3) {
            throw "Legacy bindings require host Qt 6.5.3: $dll"
        }
    }
    $python = Get-ToolkitHostVersion (Get-ToolkitSafePath $Root 'python311.dll')
    if ($python.FileMajorPart -ne 3 -or $python.FileMinorPart -ne 11) { throw 'Legacy bindings require host CPython 3.11.' }
    # Existing third-party bindings are never replaced. A second install is
    # accepted only when the exact complete toolkit runtime is already present.
    foreach ($folder in @('python/Lib/site-packages/PySide6','python/Lib/site-packages/shiboken6')) {
        $directory = Get-ToolkitSafePath $Root $folder
        if (Test-Path -LiteralPath $directory) {
            if (!(Test-Path -LiteralPath $directory -PathType Container)) { throw "A file occupies runtime directory: $folder" }
            $runtimeFiles=@($Manifest.files | Where-Object { $_.profile -eq 'legacy' -and $_.target.StartsWith($folder+'/',[StringComparison]::Ordinal) })
            if (Test-ToolkitCacheOnlyDirectory $Root $folder $runtimeFiles) { continue }
            foreach ($file in $runtimeFiles) {
                $target = Get-ToolkitSafePath $Root $file.target
                if (!(Test-Path -LiteralPath $target -PathType Leaf) -or (Get-ToolkitHash $target) -cne $file.sha256) {
                    throw "Existing or incomplete Python bindings conflict with the legacy runtime: $($file.target). Restore the previous toolkit installation first."
                }
            }
        }
    }
    $abi = Get-ToolkitSafePath $Root 'python3.dll'
    if (Test-Path -LiteralPath $abi) {
        $expected = @($Manifest.files | Where-Object {$_.target -ceq 'python3.dll'})
        if ($expected.Count -ne 1 -or !(Test-Path -LiteralPath $abi -PathType Leaf) -or (Get-ToolkitHash $abi) -cne $expected[0].sha256) {
            throw 'An existing python3.dll conflicts with the tested CPython 3.11 stable ABI forwarder.'
        }
    }
    $proxy = Get-ToolkitSafePath $Root 'D3D11.dll'
    $native = @($Manifest.files | Where-Object {$_.target -ceq 'D3D11.dll'})[0]
    if ((Test-Path -LiteralPath $proxy -PathType Leaf) -and (Get-ToolkitHash $proxy) -ceq $native.sha256) {
        throw 'Restore the previous native toolkit installation before installing the legacy profile.'
    }
    return 'legacy'
}
function Assert-ToolkitNotRunning([string]$Root) {
    foreach ($process in @(Get-Process -Name cascadeur -ErrorAction SilentlyContinue)) {
        try { $exe = $process.MainModule.FileName } catch { throw "Cannot identify running Cascadeur PID $($process.Id); close it before installation." }
        if (!$exe) { throw "Cannot identify running Cascadeur PID $($process.Id); close it before installation." }
        if ([IO.Path]::GetFullPath($exe).Equals((Join-Path $Root 'cascadeur.exe'),[StringComparison]::OrdinalIgnoreCase)) {
            throw "Cascadeur from this installation is running (PID $($process.Id)). Close it before installation."
        }
    }
}
function Read-ToolkitManifest([string]$ReleaseRoot) {
    Assert-ToolkitNoReparse $ReleaseRoot
    $manifest = Get-Content -LiteralPath (Join-Path $ReleaseRoot 'MANIFEST-SHA256.json') -Raw -Encoding UTF8 | ConvertFrom-Json
    if ($manifest.schema -ne 1 -or $manifest.product -cne $script:Product -or $manifest.release -cne $script:Release) { throw 'Wrong release manifest.' }
    $targets = New-Object 'Collections.Generic.HashSet[string]' ([StringComparer]::OrdinalIgnoreCase)
    $sources = New-Object 'Collections.Generic.HashSet[string]' ([StringComparer]::OrdinalIgnoreCase)
    foreach ($file in $manifest.files) {
        Assert-ToolkitTarget $file.target
        if ($file.profile -cnotin @('all','native','legacy')) { throw 'Invalid payload profile.' }
        if (($file.target -cin $script:LegacyRuntimeTargets) -ne ($file.profile -ceq 'legacy')) { throw 'Invalid legacy runtime target profile.' }
        if ($file.target -ceq 'D3D11.dll' -and $file.profile -cne 'native') { throw 'D3D11 proxy is only for the native profile.' }
        if ($file.source -cne ('payload/'+$file.target)) { throw "Unexpected payload source: $($file.source)" }
        if (!$targets.Add([string]$file.target) -or !$sources.Add([string]$file.source)) { throw 'Duplicate payload path.' }
        $path = Get-ToolkitSafePath $ReleaseRoot $file.source
        if (!(Test-Path -LiteralPath $path -PathType Leaf) -or $file.sha256 -notmatch '^[A-Fa-f0-9]{64}$' -or $file.size -lt 0 -or
            (Get-Item -LiteralPath $path).Length -ne $file.size -or (Get-ToolkitHash $path) -cne $file.sha256.ToUpperInvariant()) { throw "Payload integrity failed: $($file.source)" }
    }
    foreach ($runtimeTarget in $script:LegacyRuntimeTargets) {
        if (!$targets.Contains($runtimeTarget)) { throw "Incomplete legacy runtime: $runtimeTarget" }
    }
    foreach ($mandatory in @('D3D11.dll','resources/scripts/python/scripts/vmd_bridge/__init__.py','resources/scripts/python/scripts/vmd_bridge/vmd_en.qm','resources/scripts/python/commands/mmd_toolkit/__init__.py','resources/scripts/python/events/scene_activated/vmd_menu_inject.py')) {
        if (!$targets.Contains($mandatory)) { throw "Incomplete runtime: $mandatory" }
    }
    foreach ($item in Get-ChildItem -LiteralPath (Join-Path $ReleaseRoot 'payload') -File -Recurse -Force) {
        $rel = $item.FullName.Substring($ReleaseRoot.TrimEnd('\').Length+1).Replace('\','/')
        if (!$sources.Contains($rel)) { throw "Unlisted payload file: $rel" }
        Assert-ToolkitNoReparse $item.FullName
    }
    $packagePaths = New-Object 'Collections.Generic.HashSet[string]' ([StringComparer]::OrdinalIgnoreCase)
    foreach ($file in $manifest.package_files) {
        if (!$packagePaths.Add([string]$file.path) -or $file.path.Contains('/') -or $file.path.Contains('\') -or $file.path -eq 'MANIFEST-SHA256.json') { throw 'Invalid release document list.' }
        $path = Get-ToolkitSafePath $ReleaseRoot $file.path
        if (!(Test-Path -LiteralPath $path -PathType Leaf) -or (Get-Item -LiteralPath $path).Length -ne $file.size -or (Get-ToolkitHash $path) -cne $file.sha256) { throw "Release file integrity failed: $($file.path)" }
    }
    $retired = New-Object 'Collections.Generic.HashSet[string]' ([StringComparer]::OrdinalIgnoreCase)
    # Explicitly known obsolete toolkit files only. Unknown files are never removed.
    $allowedRetired = @('assets/E3_world_pose_0_144.fbx','assets/template_rest.json','e8.py','fbx_resize.py','runtime_binding.py','deps/cascadeur_vmd/mmd_solver.py') | ForEach-Object { 'resources/scripts/python/scripts/vmd_bridge/'+$_ }
    $allowedRetired += 'resources/scripts/python/events/application_started/vmd_import_menu.py'
    foreach ($relative in $manifest.retired_targets) {
        [void](Get-ToolkitSafePath $ReleaseRoot $relative)
        if ($relative -cnotin $allowedRetired -or $targets.Contains($relative) -or !$retired.Add([string]$relative)) { throw "Invalid retired target: $relative" }
    }
    return $manifest
}
function Assert-ToolkitOwnedDll([string]$Path) {
    if (!(Test-Path -LiteralPath $Path -PathType Leaf)) { return }
    $pe=Get-ToolkitPe $Path
    if ($pe.Machine -ne 34404 -or !$pe.Exports.Contains('D3D11CreateDevice') -or !$pe.Exports.Contains('D3D11CreateDeviceAndSwapChain')) { throw 'The existing D3D11.dll is not a recognized x64 Direct3D proxy or runtime.' }
    $raw = [Text.Encoding]::ASCII.GetString([IO.File]::ReadAllBytes($Path))
    $version = [Diagnostics.FileVersionInfo]::GetVersionInfo($Path)
    if ($version.ProductName -ceq $script:Product -and $version.OriginalFilename -ieq 'D3D11.dll' -and $raw.Contains('wrong vmd_bridge package: ') -and $raw.Contains('_on_import_vmd')) { return }
    # Legacy releases predate VERSIONINFO. The complete import bootstrap and
    # callback diagnostic together identify our proxy; a stray package-name
    # string in an unrelated binary is insufficient.
    if ($raw.Contains('wrong vmd_bridge package: ') -and $raw.Contains('QtCore.QTimer.singleShot(0, vmd_bridge._on_import_vmd)') -and $raw.Contains('cb: Python pipeline request accepted')) { return }
    if ($version.CompanyName -eq 'Microsoft Corporation' -and $version.OriginalFilename -ieq 'D3D11.dll' -and $version.FileDescription -eq 'Direct3D 11 Runtime') { return }
    throw 'An unrecognized D3D11.dll already exists. It may belong to another plugin; the installer will not overwrite it.'
}
function Assert-ToolkitDestination([string]$Root, [string]$Relative) {
    $path = Get-ToolkitSafePath $Root $Relative
    if (Test-Path -LiteralPath $path -PathType Container) { throw "A directory occupies a file target: $Relative" }
    $parent = [IO.Directory]::GetParent($path)
    while ($parent -and !$parent.FullName.Equals($Root,[StringComparison]::OrdinalIgnoreCase)) {
        if (Test-Path -LiteralPath $parent.FullName -PathType Leaf) { throw "A file occupies a required directory: $($parent.FullName)" }
        $parent = $parent.Parent
    }
    if (Test-Path -LiteralPath $path -PathType Leaf) {
        # Read with exclusive sharing detects open/locked targets without requiring
        # write permission before the visible entry point can request UAC.
        $handle = [IO.File]::Open($path,[IO.FileMode]::Open,[IO.FileAccess]::Read,[IO.FileShare]::None)
        $handle.Dispose()
        if ((Get-Item -LiteralPath $path -Force).IsReadOnly) { throw "Target is read-only: $Relative" }
    }
    return $path
}
function Write-ToolkitBytes([string]$Source, [string]$Destination) {
    $inputStream = [IO.File]::OpenRead($Source)
    try {
        $outputStream = [IO.File]::Open($Destination,[IO.FileMode]::Create,[IO.FileAccess]::Write,[IO.FileShare]::None)
        try { $inputStream.CopyTo($outputStream); $outputStream.Flush($true) } finally { $outputStream.Dispose() }
    } finally { $inputStream.Dispose() }
}
function Get-ToolkitVerification([string]$Path, [string]$ExpectedHash, [long]$ExpectedSize, [bool]$RequireFresh) {
    $hash = Get-ToolkitHash $Path
    $item = Get-Item -LiteralPath $Path -Force
    $verified = [DateTime]::UtcNow
    $age = ($verified - $item.LastWriteTimeUtc).TotalSeconds
    if ($hash -cne $ExpectedHash -or $item.Length -ne $ExpectedSize -or ($RequireFresh -and ($age -lt -2 -or $age -gt 300))) {
        throw "Hash/size/write-time verification failed: $Path (age $age seconds)"
    }
    [ordered]@{ sha256=$hash; size=$item.Length; last_write_time_utc=$item.LastWriteTimeUtc.ToString('o'); verified_utc=$verified.ToString('o'); age_seconds=$age; written=$RequireFresh }
}
function New-ToolkitParents([string]$Path, [string]$Root, [object]$Journal) {
    $missing = New-Object 'Collections.Generic.List[string]'
    $parent = [IO.Directory]::GetParent($Path)
    while ($parent -and !(Test-Path -LiteralPath $parent.FullName)) { $missing.Add($parent.FullName); $parent=$parent.Parent }
    for ($i=$missing.Count-1; $i -ge 0; $i--) {
        [void][IO.Directory]::CreateDirectory($missing[$i])
        $Journal.created_directories.Add($missing[$i].Substring($Root.Length+1).Replace('\','/'))
    }
}
function Undo-ToolkitTransaction([object]$Journal, [string]$BackupDirectory) {
    $errors = New-Object 'Collections.Generic.List[string]'
    for ($i=$Journal.entries.Count-1; $i -ge 0; $i--) {
        $entry = $Journal.entries[$i]
        if (!$entry.mutated -or $entry.restored) { continue }
        try {
            $target = Get-ToolkitSafePath $Journal.install_root $entry.target
            if ($entry.existed) {
                $backup = Get-ToolkitSafePath $BackupDirectory ('files/'+$entry.target)
                if ((Get-ToolkitHash $backup) -cne $entry.before_sha256) { throw 'Backup checksum mismatch.' }
                Write-ToolkitBytes $backup $target
                $entry.rollback_verification = Get-ToolkitVerification $target $entry.before_sha256 $entry.before_size $true
            } elseif (Test-Path -LiteralPath $target -PathType Leaf) { Remove-Item -LiteralPath $target -Force }
            elseif (Test-Path -LiteralPath $target) { throw 'A new target became a directory; automatic removal was refused.' }
            $entry.restored = $true
        } catch { $errors.Add($entry.target+': '+$_.Exception.Message) }
    }
    for ($i=$Journal.created_directories.Count-1; $i -ge 0; $i--) {
        try {
            $relative=$Journal.created_directories[$i]
            $parentDirs=@('python','python/Lib','python/Lib/site-packages','python/Lib/site-packages/PySide6','python/Lib/site-packages/PySide6/support','python/Lib/site-packages/shiboken6','resources','resources/scripts','resources/scripts/python','resources/scripts/python/scripts','resources/scripts/python/scripts/vmd_bridge','resources/scripts/python/commands','resources/scripts/python/commands/mmd_toolkit','resources/scripts/python/events','resources/scripts/python/events/scene_activated')
            if ($relative -cnotin $parentDirs -and !$relative.StartsWith('resources/scripts/python/scripts/vmd_bridge/',[StringComparison]::Ordinal) -and !$relative.StartsWith('resources/scripts/python/commands/mmd_toolkit/',[StringComparison]::Ordinal)) { throw 'Invalid created-directory record.' }
            $dir = Get-ToolkitSafePath $Journal.install_root $relative
            if ((Test-Path -LiteralPath $dir -PathType Container) -and @(Get-ChildItem -LiteralPath $dir -Force).Count -eq 0) { [IO.Directory]::Delete($dir) }
        } catch { $errors.Add($_.Exception.Message) }
    }
    return $errors.ToArray()
}
function Update-ToolkitFailureObservation([object]$Journal) {
    # A failed rollback may itself have partially written a target. Record the
    # current readable bytes after that attempt so a later restore can retry
    # without accepting arbitrary subsequent edits.
    foreach ($entry in $Journal.entries) {
        if (!$entry.mutated -or $entry.restored) { continue }
        try {
            $target=Get-ToolkitSafePath $Journal.install_root $entry.target
            if (Test-Path -LiteralPath $target -PathType Leaf) { $entry.observed_after_failure_sha256=Get-ToolkitHash $target }
        } catch { }
    }
}
function New-ToolkitMutex([string]$Root) {
    $algorithm = [Security.Cryptography.SHA256]::Create()
    try { $id = [BitConverter]::ToString($algorithm.ComputeHash([Text.Encoding]::UTF8.GetBytes($Root.ToUpperInvariant()))).Replace('-','') } finally { $algorithm.Dispose() }
    $mutex = New-Object Threading.Mutex($false,('Local\CascadeurMMDToolkit_'+$id))
    try { $entered = $mutex.WaitOne(0) } catch [Threading.AbandonedMutexException] { $entered=$true }
    if (!$entered) { $mutex.Dispose(); throw 'Another toolkit install or restore is using this installation.' }
    return $mutex
}
function Invoke-ToolkitInstall([string]$ReleaseRoot, [string]$CascadeurRoot, [string]$BackupDirectory, [switch]$Preview) {
    $ReleaseRoot = [IO.Path]::GetFullPath($ReleaseRoot).TrimEnd('\')
    $root = Get-ToolkitRoot $CascadeurRoot
    if ($root.StartsWith($ReleaseRoot+'\',[StringComparison]::OrdinalIgnoreCase) -or $ReleaseRoot.StartsWith($root+'\',[StringComparison]::OrdinalIgnoreCase) -or $root -ieq $ReleaseRoot) { throw 'Release and installation directories must be separate.' }
    $manifest = Read-ToolkitManifest $ReleaseRoot
    $hostProfile = Get-ToolkitHostProfile $root $manifest
    Assert-ToolkitNotRunning $root
    $mutex = New-ToolkitMutex $root
    try {
        $entries = New-Object 'Collections.Generic.List[object]'
        foreach ($file in $manifest.files | Where-Object {$_.profile -ceq 'all' -or $_.profile -ceq $hostProfile}) {
            $target = Get-ToolkitSafePath $root $file.target
            $exists = Test-Path -LiteralPath $target -PathType Leaf
            $same = $exists -and (Get-Item -LiteralPath $target).Length -eq $file.size -and (Get-ToolkitHash $target) -ceq $file.sha256
            if (!$same) {
                [void](Assert-ToolkitDestination $root $file.target)
                if ($file.target -ceq 'D3D11.dll') { Assert-ToolkitOwnedDll $target }
            }
            $entries.Add([ordered]@{ target=$file.target; source=$file.source; action=$(if($same){'unchanged'}else{'write'}); expected_sha256=$file.sha256; expected_size=$file.size; existed=[bool]$exists; before_sha256=$(if($exists){Get-ToolkitHash $target}else{$null}); before_size=$(if($exists){(Get-Item -LiteralPath $target).Length}else{0}); mutated=$false; restored=$false; verification=$null; rollback_verification=$null; observed_after_failure_sha256=$null })
        }
        foreach ($relative in $manifest.retired_targets) {
            $target = Get-ToolkitSafePath $root $relative
            if (Test-Path -LiteralPath $target) {
                [void](Assert-ToolkitDestination $root $relative)
                $entries.Add([ordered]@{target=$relative; source=$null; action='remove_retired'; expected_sha256=$null; expected_size=0; existed=$true; before_sha256=(Get-ToolkitHash $target); before_size=(Get-Item -LiteralPath $target).Length; mutated=$false; restored=$false; verification=$null; rollback_verification=$null; observed_after_failure_sha256=$null})
            }
        }
        $journal = [ordered]@{ schema=1; product=$script:Product; release=$script:Release; install_root=$root; release_root=$ReleaseRoot; started_utc=[DateTime]::UtcNow.ToString('o'); completed_utc=$null; status='preview'; host_profile=$hostProfile; host_version=(Get-ToolkitHostRelease $root).ToString(); error=$null; rollback_errors=@(); entries=$entries; created_directories=(New-Object 'Collections.Generic.List[string]') }
        if ($Preview) { return $journal }
        $BackupDirectory = [IO.Path]::GetFullPath($BackupDirectory).TrimEnd('\')
        Assert-ToolkitNoReparse $BackupDirectory
        if ((Test-Path -LiteralPath $BackupDirectory) -or $BackupDirectory.StartsWith($root+'\',[StringComparison]::OrdinalIgnoreCase) -or $BackupDirectory -ieq $root) { throw 'Backup directory must be new and outside the installation.' }
        [void][IO.Directory]::CreateDirectory($BackupDirectory)
        $journalPath = Join-Path $BackupDirectory 'journal.json'
        $journal.status='backing_up'
        Write-ToolkitJson $journal $journalPath
        try {
            foreach ($entry in $entries) {
                if ($entry.action -eq 'unchanged' -or !$entry.existed) { continue }
                $target = Get-ToolkitSafePath $root $entry.target
                $backup = Get-ToolkitSafePath $BackupDirectory ('files/'+$entry.target)
                [void][IO.Directory]::CreateDirectory([IO.Path]::GetDirectoryName($backup))
                Write-ToolkitBytes $target $backup
                [void](Get-ToolkitVerification $backup $entry.before_sha256 $entry.before_size $true)
            }
            $journal.status='installing'; Write-ToolkitJson $journal $journalPath
            foreach ($entry in $entries) {
                $target = Get-ToolkitSafePath $root $entry.target
                if ($entry.action -eq 'unchanged') {
                    $entry.verification = Get-ToolkitVerification $target $entry.expected_sha256 $entry.expected_size $false
                    continue
                }
                Assert-ToolkitNotRunning $root
                [void](Assert-ToolkitDestination $root $entry.target)
                # Detect a race or a changed payload before touching this destination.
                if ($entry.existed -and (Get-ToolkitHash $target) -cne $entry.before_sha256) { throw "Target changed after backup: $($entry.target)" }
                if (!$entry.existed -and (Test-Path -LiteralPath $target)) { throw "New target appeared during installation: $($entry.target)" }
                if ($entry.action -eq 'write') {
                    $source = Get-ToolkitSafePath $ReleaseRoot $entry.source
                    if ((Get-ToolkitHash $source) -cne $entry.expected_sha256 -or (Get-Item -LiteralPath $source).Length -ne $entry.expected_size) { throw "Payload changed during installation: $($entry.source)" }
                    New-ToolkitParents $target $root $journal
                }
                $entry.mutated=$true; Write-ToolkitJson $journal $journalPath
                if ($entry.action -eq 'remove_retired') { Remove-Item -LiteralPath $target -Force }
                else { Write-ToolkitBytes $source $target; $entry.verification=Get-ToolkitVerification $target $entry.expected_sha256 $entry.expected_size $true }
                Write-ToolkitJson $journal $journalPath
            }
            foreach ($entry in $entries) {
                $target = Get-ToolkitSafePath $root $entry.target
                if ($entry.action -eq 'remove_retired') { if(Test-Path -LiteralPath $target){throw "Retired file still exists: $($entry.target)"} }
                else { $entry.verification=Get-ToolkitVerification $target $entry.expected_sha256 $entry.expected_size ($entry.action -eq 'write') }
            }
            $journal.status='installed'; $journal.completed_utc=[DateTime]::UtcNow.ToString('o'); Write-ToolkitJson $journal $journalPath
            return $journal
        } catch {
            $journal.error=$_.Exception.Message
            foreach ($entry in $entries) {
                if (!$entry.mutated) { continue }
                try {
                    $target=Get-ToolkitSafePath $root $entry.target
                    if (Test-Path -LiteralPath $target -PathType Leaf) { $entry.observed_after_failure_sha256=Get-ToolkitHash $target }
                } catch { } # An exclusive lock can prevent observing partial bytes.
            }
            $journal.rollback_errors=@(Undo-ToolkitTransaction $journal $BackupDirectory)
            Update-ToolkitFailureObservation $journal
            $journal.status=$(if($journal.rollback_errors.Count){'failed_rollback_incomplete'}else{'failed_rolled_back'})
            $journal.completed_utc=[DateTime]::UtcNow.ToString('o'); Write-ToolkitJson $journal $journalPath
            throw "Installation failed: $($journal.error) | Status: $($journal.status) | Backup: $BackupDirectory"
        }
    } finally { $mutex.ReleaseMutex(); $mutex.Dispose() }
}
function Invoke-ToolkitRestore([string]$BackupDirectory) {
    $BackupDirectory = [IO.Path]::GetFullPath($BackupDirectory).TrimEnd('\')
    Assert-ToolkitNoReparse $BackupDirectory
    $journalPath = Join-Path $BackupDirectory 'journal.json'
    $journal = Get-Content -LiteralPath $journalPath -Raw -Encoding UTF8 | ConvertFrom-Json
    $statuses=@('installed','failed_rollback_incomplete','restore_incomplete','installing','restoring','failed_rolled_back','restored')
    if ($journal.schema -ne 1 -or $journal.product -cne $script:Product -or $journal.release -cne $script:Release -or $journal.status -notin $statuses) { throw 'Choose a toolkit 1.0 installation backup with a recorded transaction.' }
    if ($journal.status -in @('restored','failed_rolled_back')) { return $journal }
    $recovering=$journal.status -ne 'installed'
    $root = Get-ToolkitRoot $journal.install_root
    Assert-ToolkitNotRunning $root
    $mutex = New-ToolkitMutex $root
    try {
        $seen = New-Object 'Collections.Generic.HashSet[string]' ([StringComparer]::OrdinalIgnoreCase)
        foreach ($entry in $journal.entries) {
            if (!$seen.Add([string]$entry.target)) { throw 'Duplicate target in backup journal.' }
            if (!$entry.mutated) { continue }
            if ($entry.action -eq 'remove_retired') {
                $allowed = @('assets/E3_world_pose_0_144.fbx','assets/template_rest.json','e8.py','fbx_resize.py','runtime_binding.py','deps/cascadeur_vmd/mmd_solver.py') | ForEach-Object {'resources/scripts/python/scripts/vmd_bridge/'+$_}
                $allowed += 'resources/scripts/python/events/application_started/vmd_import_menu.py'
                if ($entry.target -cnotin $allowed) { throw 'Invalid retired target in journal.' }
            } elseif ($entry.action -eq 'write') { Assert-ToolkitTarget $entry.target }
            else { throw 'Invalid mutation action in journal.' }
            $target = Get-ToolkitSafePath $root $entry.target
            if ($entry.existed) {
                $backup = Get-ToolkitSafePath $BackupDirectory ('files/'+$entry.target)
                [void](Get-ToolkitVerification $backup $entry.before_sha256 $entry.before_size $false)
            }
            $exists=Test-Path -LiteralPath $target -PathType Leaf
            $currentHash=$(if($exists){Get-ToolkitHash $target}else{$null})
            if ($recovering -and (($entry.existed -and $currentHash -ceq $entry.before_sha256) -or (!$entry.existed -and !(Test-Path -LiteralPath $target)))) {
                $entry.restored=$true
                continue
            }
            if ($entry.restored) { throw "Previously restored target changed; restore refused: $($entry.target)" }
            if ($entry.action -eq 'remove_retired') { if(Test-Path -LiteralPath $target){throw "Retired path changed since installation: $($entry.target)"} }
            elseif (!$exists -or ($currentHash -cne $entry.expected_sha256 -and !($recovering -and $entry.observed_after_failure_sha256 -and $currentHash -ceq $entry.observed_after_failure_sha256))) { throw "Target changed since installation; restore refused: $($entry.target)" }
            [void](Assert-ToolkitDestination $root $entry.target)
        }
        $journal.status='restoring'; Write-ToolkitJson $journal $journalPath
        $journal.rollback_errors=@(Undo-ToolkitTransaction $journal $BackupDirectory)
        Update-ToolkitFailureObservation $journal
        $journal.status=$(if($journal.rollback_errors.Count){'restore_incomplete'}else{'restored'})
        $journal.completed_utc=[DateTime]::UtcNow.ToString('o'); Write-ToolkitJson $journal $journalPath
        if ($journal.rollback_errors.Count) { throw ('Restore incomplete: '+($journal.rollback_errors -join '; ')) }
        return $journal
    } finally { $mutex.ReleaseMutex(); $mutex.Dispose() }
}
function Test-ToolkitWritable([string]$Root) {
    $probe = Join-Path $Root ('.toolkit-write-check-'+[Guid]::NewGuid().ToString('N')+'.tmp')
    try {
        $stream = New-Object IO.FileStream($probe,[IO.FileMode]::CreateNew,[IO.FileAccess]::Write,[IO.FileShare]::None,1,[IO.FileOptions]::DeleteOnClose)
        $stream.Dispose(); return $true
    } catch [UnauthorizedAccessException] { return $false }
}
function Test-ToolkitAdministrator {
    $identity=[Security.Principal.WindowsIdentity]::GetCurrent()
    (New-Object Security.Principal.WindowsPrincipal($identity)).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}
function ConvertTo-ToolkitLiteral([string]$Value) { return "'"+$Value.Replace("'","''")+"'" }
Export-ModuleMember -Function *-Toolkit*
