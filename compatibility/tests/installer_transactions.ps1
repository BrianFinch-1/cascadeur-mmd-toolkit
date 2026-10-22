param(
    [Parameter(Mandatory=$true)][string]$ReleaseRoot,
    [Parameter(Mandatory=$true)][string]$HostRoot,
    [string]$ModernHostRoot,
    [string]$PortableVersionFixture
)
$ErrorActionPreference='Stop'
$ReleaseRoot=[IO.Path]::GetFullPath($ReleaseRoot)
$HostRoot=[IO.Path]::GetFullPath($HostRoot)
$module=Import-Module (Join-Path $ReleaseRoot 'Installer.Core.psm1') -Force -PassThru -DisableNameChecking
if ($PortableVersionFixture) {
    # Linux harness: adapt only Windows path interpretation and VERSIONINFO
    # access. Versions must be extracted from the real host PE files. The
    # manifest, PE export parser, profile selection and transactions are real.
    $versions=Get-Content -LiteralPath $PortableVersionFixture -Raw | ConvertFrom-Json
    & $module {
        param($versions, $modernRoot)
        $script:TestVersions=$versions.legacy
        $script:ModernTestVersions=$versions.modern
        $script:ModernTestRoot=$modernRoot
        function script:Get-ToolkitHostVersion([string]$Path) {
            if ($script:ModernTestRoot -and $Path.StartsWith($script:ModernTestRoot+'/',[StringComparison]::Ordinal)) {
                return $script:ModernTestVersions.([IO.Path]::GetFileName($Path))
            }
            return $script:TestVersions.([IO.Path]::GetFileName($Path))
        }
        function script:Get-ToolkitRoot([string]$Path) {
            $full=[IO.Path]::GetFullPath($Path)
            if (!(Test-Path -LiteralPath $full -PathType Container)) { throw 'Missing test host' }
            return $full
        }
        function script:Get-ToolkitSafePath([string]$Root,[string]$Relative) {
            if (!$Relative -or $Relative.Contains('\') -or $Relative.StartsWith('/') -or $Relative.Contains(':') -or
                @($Relative.Split('/') | Where-Object {$_ -in @('','.', '..')}).Count) { throw 'Invalid test path' }
            $full=[IO.Path]::GetFullPath((Join-Path $Root $Relative))
            if (!$full.StartsWith($Root.TrimEnd('/')+'/',[StringComparison]::Ordinal)) { throw 'Path leaves test root' }
            Assert-ToolkitNoReparse $full
            return $full
        }
    } $versions $ModernHostRoot
}
function Assert([bool]$Condition,[string]$Message) { if (!$Condition) { throw $Message } }
function Expect-Failure([scriptblock]$Action,[string]$Pattern) {
    try { & $Action | Out-Null } catch {
        if ($_.Exception.Message -notlike ('*'+$Pattern+'*')) { throw }
        return
    }
    throw ('Expected failure: '+$Pattern)
}
function Snapshot([string]$Root) {
    return (@(Get-ChildItem -LiteralPath $Root -Recurse -Force | Sort-Object FullName | ForEach-Object {
        $relative=$_.FullName.Substring($Root.Length)
        if ($_.PSIsContainer) { 'D '+$relative } else { 'F '+$relative+' '+(Get-ToolkitHash $_.FullName) }
    }) -join "`n")
}
$temporary=Join-Path ([IO.Path]::GetTempPath()) ('mmd-installer-test-'+[Guid]::NewGuid().ToString('N'))
[void][IO.Directory]::CreateDirectory($temporary)
try {
    $root=Join-Path $temporary 'host'
    [void][IO.Directory]::CreateDirectory($root)
    $manifest=Read-ToolkitManifest $ReleaseRoot
    if ($ModernHostRoot) {
        $modernBefore=Get-ToolkitHash (Join-Path $ModernHostRoot 'python/Lib/site-packages/PySide6/QtCore.pyd')
        $modern=Invoke-ToolkitInstall -ReleaseRoot $ReleaseRoot -CascadeurRoot $ModernHostRoot -Preview
        Assert ($modern.host_profile -ceq 'native') 'Modern host did not select native profile'
        Assert (@($modern.entries | Where-Object {$_.target -ceq 'D3D11.dll'}).Count -eq 1) 'Modern native proxy missing'
        Assert (@($modern.entries | Where-Object {$_.target -like 'python/*' -or $_.target -ceq 'python3.dll'}).Count -eq 0) 'Modern Python runtime would be overwritten'
        Assert ((Get-ToolkitHash (Join-Path $ModernHostRoot 'python/Lib/site-packages/PySide6/QtCore.pyd')) -ceq $modernBefore) 'Modern binding modified'
        Write-Output 'PASS: modern host capability preflight and native profile preserve host bindings'
    }
    foreach ($relative in @($manifest.legacy_requirements.files)+@($manifest.legacy_requirements.native | ForEach-Object {$_.path})) {
        $destination=Join-Path $root $relative
        [void][IO.Directory]::CreateDirectory([IO.Path]::GetDirectoryName($destination))
        Copy-Item -LiteralPath (Join-Path $HostRoot $relative) -Destination $destination
    }
    foreach ($relative in $manifest.legacy_requirements.directories) { [void][IO.Directory]::CreateDirectory((Join-Path $root $relative)) }
    $before=Snapshot $root
    $preview=Invoke-ToolkitInstall -ReleaseRoot $ReleaseRoot -CascadeurRoot $root -Preview
    Assert ($preview.host_profile -eq 'legacy') 'Wrong host profile'
    Assert (@($preview.entries | Where-Object {$_.target -eq 'D3D11.dll'}).Count -eq 0) 'Legacy proxy must not be installed'
    Assert (@($preview.entries | Where-Object {$_.target -like '*QtGui.pyd' -or $_.target -like '*QtQuick.pyd'}).Count -eq 0) 'Incompatible GUI bindings must not be installed'
    Assert ((Snapshot $root) -ceq $before) 'Preview changed host'
    Write-Output 'PASS: legacy profile, complete capability preflight, preview is read-only'

    $backup=Join-Path $temporary 'backup'
    $journal=Invoke-ToolkitInstall -ReleaseRoot $ReleaseRoot -CascadeurRoot $root -BackupDirectory $backup
    Assert ($journal.status -eq 'installed') 'Install failed'
    $again=Invoke-ToolkitInstall -ReleaseRoot $ReleaseRoot -CascadeurRoot $root -Preview
    Assert (@($again.entries | Where-Object {$_.action -ne 'unchanged'}).Count -eq 0) 'Repeated install is not idempotent'
    Write-Output 'PASS: install and idempotent reinstall'

    $tampered=Join-Path $root 'resources/scripts/python/scripts/vmd_bridge/native/qt_list_ref.dll'
    [IO.File]::AppendAllText($tampered,'changed')
    Expect-Failure {Invoke-ToolkitRestore $backup} 'Target changed since installation'
    Copy-Item -LiteralPath (Join-Path $ReleaseRoot 'payload/resources/scripts/python/scripts/vmd_bridge/native/qt_list_ref.dll') -Destination $tampered -Force
    $restored=Invoke-ToolkitRestore $backup
    Assert ($restored.status -eq 'restored') 'Restore failed'
    Assert ((Snapshot $root) -ceq $before) 'Restore did not return exact initial host tree'
    Write-Output 'PASS: changed-file restore refusal and exact restore of files/directories'

    # A real Python process leaves these after restoring source/runtime files.
    $caches=@(
        'python/Lib/site-packages/PySide6/__pycache__/__init__.cpython-311.pyc',
        'python/Lib/site-packages/PySide6/support/__pycache__/deprecated.cpython-311.opt-1.pyc',
        'python/Lib/site-packages/shiboken6/__pycache__/__init__.cpython-311.pyc'
    )
    foreach ($relative in $caches) {
        $cache=Join-Path $root $relative
        [void][IO.Directory]::CreateDirectory([IO.Path]::GetDirectoryName($cache))
        [IO.File]::WriteAllBytes($cache,[byte[]](1,2,3,4))
    }
    $cacheBefore=Snapshot $root
    $cachedPreview=Invoke-ToolkitInstall -ReleaseRoot $ReleaseRoot -CascadeurRoot $root -Preview
    Assert ($cachedPreview.host_profile -ceq 'legacy') 'Cache-only package remnants block reinstall'
    $cacheBackup=Join-Path $temporary 'backup-cache'
    [void](Invoke-ToolkitInstall -ReleaseRoot $ReleaseRoot -CascadeurRoot $root -BackupDirectory $cacheBackup)
    [void](Invoke-ToolkitRestore $cacheBackup)
    Assert ((Snapshot $root) -ceq $cacheBefore) 'Restore modified pre-existing bytecode caches'
    $unknownCache=Join-Path $root 'python/Lib/site-packages/PySide6/__pycache__/foreign.cpython-311.pyc'
    [IO.File]::WriteAllBytes($unknownCache,[byte[]](1,2,3,4))
    Expect-Failure {Invoke-ToolkitInstall -ReleaseRoot $ReleaseRoot -CascadeurRoot $root -Preview} 'bindings conflict'
    Remove-Item -LiteralPath (Join-Path $root 'python/Lib/site-packages/PySide6') -Recurse -Force
    Remove-Item -LiteralPath (Join-Path $root 'python/Lib/site-packages/shiboken6') -Recurse -Force
    Write-Output 'PASS: known cache-only remnants reinstall, restore preserves them, unknown caches rejected'

    if ($PortableVersionFixture) {
        $originalVersion=& $module {$script:TestVersions.'cascadeur.exe'.FileVersion}
        try {
            & $module {$script:TestVersions.'cascadeur.exe'.FileVersion='2026.1.2.0.1'}
            Expect-Failure {Invoke-ToolkitInstall -ReleaseRoot $ReleaseRoot -CascadeurRoot $root -Preview} '2026.1.3 or later'
            & $module {$script:TestVersions.'cascadeur.exe'.FileVersion='2026.2.0.0.1'}
            Expect-Failure {Invoke-ToolkitInstall -ReleaseRoot $ReleaseRoot -CascadeurRoot $root -Preview} 'Missing host capability'
            & $module {$script:TestVersions.'cascadeur.exe'.FileVersion='unknown'}
            Expect-Failure {Invoke-ToolkitInstall -ReleaseRoot $ReleaseRoot -CascadeurRoot $root -Preview} 'Cannot identify the Cascadeur release'
        } finally { & $module {param($v) $script:TestVersions.'cascadeur.exe'.FileVersion=$v} $originalVersion }
        $mixedRule=Join-Path $root 'resources/scripts/python/python_actions_rule.py'
        [IO.File]::WriteAllText($mixedRule,'mixed host scripting rules')
        Expect-Failure {Invoke-ToolkitInstall -ReleaseRoot $ReleaseRoot -CascadeurRoot $root -Preview} 'mixed scripting rules'
        Remove-Item -LiteralPath $mixedRule
        Assert ((Snapshot $root) -ceq $before) 'Version rejection modified host'
        Write-Output 'PASS: unsupported/unidentifiable versions and mixed rules rejected; modern never falls back to legacy'
    }

    $foreign=Join-Path $root 'python/Lib/site-packages/PySide6/__init__.py'
    [void][IO.Directory]::CreateDirectory([IO.Path]::GetDirectoryName($foreign))
    [IO.File]::WriteAllText($foreign,'third-party bindings')
    $foreignBefore=Snapshot $root
    Expect-Failure {Invoke-ToolkitInstall -ReleaseRoot $ReleaseRoot -CascadeurRoot $root -Preview} 'bindings conflict'
    Assert ((Snapshot $root) -ceq $foreignBefore) 'Conflicting bindings were modified'
    Remove-Item -LiteralPath ([IO.Path]::GetDirectoryName($foreign)) -Recurse -Force
    Write-Output 'PASS: unknown/partial bindings are preserved and rejected before writes'

    # Existing toolkit source must be backed up and restored, not merely removed.
    $existing=Join-Path $root 'resources/scripts/python/scripts/vmd_bridge/__init__.py'
    [void][IO.Directory]::CreateDirectory([IO.Path]::GetDirectoryName($existing))
    [IO.File]::WriteAllText($existing,'previous toolkit source')
    $before=Snapshot $root
    $backup=Join-Path $temporary 'backup-existing'
    [void](Invoke-ToolkitInstall -ReleaseRoot $ReleaseRoot -CascadeurRoot $root -BackupDirectory $backup)
    [void](Invoke-ToolkitRestore $backup)
    Assert ((Snapshot $root) -ceq $before) 'Existing source was not restored'
    Write-Output 'PASS: existing toolkit file restored from verified backup'

    & $module {
        $script:RealWriter=${function:Write-ToolkitBytes}
        $script:WriteCounter=0
        function script:Write-ToolkitBytes([string]$Source,[string]$Destination) {
            $script:WriteCounter++
            if ($script:WriteCounter -eq 5) { throw 'Injected write failure' }
            & $script:RealWriter $Source $Destination
        }
    }
    $backup=Join-Path $temporary 'backup-failure'
    Expect-Failure {Invoke-ToolkitInstall -ReleaseRoot $ReleaseRoot -CascadeurRoot $root -BackupDirectory $backup} 'failed_rolled_back'
    Assert ((Snapshot $root) -ceq $before) 'Rollback did not return exact initial host tree'
    Write-Output 'PASS: injected mid-install failure fully rolls back'
    Write-Output 'ALL INSTALLER TRANSACTION TESTS PASSED'
} finally {
    Remove-Module $module
    Remove-Item -LiteralPath $temporary -Recurse -Force
}
