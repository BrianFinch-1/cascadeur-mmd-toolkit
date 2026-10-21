param(
    [string]$CascadeurRoot,
    [string]$BackupDirectory,
    [string]$ResultPath,
    [switch]$WhatIf,
    [switch]$FromLauncher,
    [switch]$NoPause,
    [switch]$ElevatedChild
)
$ErrorActionPreference='Stop'
$exitCode=1
$failure=$null
try {
    Import-Module -Name (Join-Path $PSScriptRoot 'Installer.Core.psm1') -Force -DisableNameChecking
    Write-Host 'cascadeur MMD toolkit 1.0' -ForegroundColor Cyan
    Write-Host '安装 / Install: 关闭此安装目录中的 Cascadeur 后继续。'
    Write-Host 'Close Cascadeur from the chosen installation before continuing.'
    if (!$CascadeurRoot) {
        Write-Host '粘贴 Cascadeur 安装根目录并按 Enter，例如 C:\Program Files\Cascadeur。'
        $CascadeurRoot=Read-Host 'Paste Cascadeur installation root, then Enter (blank = cancel / 留空取消)'
        $CascadeurRoot=$CascadeurRoot.Trim().Trim('"')
    }
    if ([string]::IsNullOrWhiteSpace($CascadeurRoot)) { Write-Host '已取消 / Cancelled.'; $exitCode=2 }
    else {
        $root=Get-ToolkitRoot $CascadeurRoot
        # Validate the entire release and host capabilities before requesting elevation.
        $preview=Invoke-ToolkitInstall -ReleaseRoot $PSScriptRoot -CascadeurRoot $root -Preview
        Write-Host ('宿主模式 / Host profile: '+$preview.host_profile)
        $writes=@($preview.entries | Where-Object {$_.action -eq 'write'}).Count
        $unchanged=@($preview.entries | Where-Object {$_.action -eq 'unchanged'}).Count
        Write-Host ("待写入 / To write: {0}; 内容相同未写入 / Same hash, not written: {1}" -f $writes,$unchanged)
        if ($WhatIf) { Write-Host '仅检查，未安装 / Preview complete; nothing installed.'; $exitCode=0 }
        else {
            if (!$BackupDirectory) {
                $BackupDirectory=Join-Path ([Environment]::GetFolderPath('LocalApplicationData')) ('cascadeur MMD toolkit\backups\'+[DateTime]::UtcNow.ToString('yyyyMMddTHHmmssZ')+'-'+[Guid]::NewGuid().ToString('N'))
            }
            $BackupDirectory=[IO.Path]::GetFullPath($BackupDirectory)
            Write-Host ('备份和安装记录 / Backup and journal: '+$BackupDirectory)
            if (!(Test-ToolkitWritable $root) -and !(Test-ToolkitAdministrator)) {
                if ($ElevatedChild) { throw 'Elevated process still cannot write to the installation.' }
                Write-Host '需要管理员权限 / Windows administrator permission is required.'
                $resultDirectory=Join-Path ([Environment]::GetFolderPath('LocalApplicationData')) 'cascadeur MMD toolkit/installer-results'
                [void][IO.Directory]::CreateDirectory($resultDirectory)
                $childResult=Join-Path $resultDirectory ([Guid]::NewGuid().ToString('N')+'.json')
                $command='& '+(ConvertTo-ToolkitLiteral (Join-Path $PSScriptRoot 'Install.ps1'))+' -CascadeurRoot '+(ConvertTo-ToolkitLiteral $root)+' -BackupDirectory '+(ConvertTo-ToolkitLiteral $BackupDirectory)+' -ResultPath '+(ConvertTo-ToolkitLiteral $childResult)+' -NoPause -ElevatedChild; exit $LASTEXITCODE'
                $encoded=[Convert]::ToBase64String([Text.Encoding]::Unicode.GetBytes($command))
                $child=Start-Process -FilePath (Join-Path $PSHOME 'powershell.exe') -ArgumentList @('-NoLogo','-NoProfile','-ExecutionPolicy','Bypass','-EncodedCommand',$encoded) -Verb RunAs -WindowStyle Hidden -PassThru -Wait
                if ($child.ExitCode -ne 0) {
                    $detail='Administrator install failed or was cancelled. Exit code: '+$child.ExitCode
                    if (Test-Path -LiteralPath $childResult -PathType Leaf) { $detail=(Get-Content -LiteralPath $childResult -Raw -Encoding UTF8 | ConvertFrom-Json).error }
                    throw $detail
                }
                $journal=Get-Content -LiteralPath (Join-Path $BackupDirectory 'journal.json') -Raw -Encoding UTF8 | ConvertFrom-Json
                if ($journal.status -ne 'installed') { throw ('Installation did not complete: '+$journal.status) }
            } else { $journal=Invoke-ToolkitInstall -ReleaseRoot $PSScriptRoot -CascadeurRoot $root -BackupDirectory $BackupDirectory }
            Write-Host '安装成功 / Installation completed.' -ForegroundColor Green
            Write-Host '现在可以启动 Cascadeur。首次安装或升级均须启动新进程。'
            Write-Host 'Start a new Cascadeur process. Installation integrity does not prove runtime loading.'
            Write-Host '恢复安装前文件：双击 Restore.cmd，粘贴上面的备份目录。'
            Write-Host 'To restore previous files, open Restore.cmd and paste the backup directory above.'
            $exitCode=0
        }
    }
} catch {
    $failure=$_.Exception.Message
    Write-Host ('失败 / Failed: '+$_.Exception.Message) -ForegroundColor Red
    Write-Host '请保留完整提示和备份目录。不要在未完成恢复时启动 Cascadeur。'
    Write-Host 'Keep this message and the backup journal. Resolve an incomplete rollback before starting Cascadeur.'
    $exitCode=1
} finally {
    if ($ResultPath) {
        try { Write-ToolkitJson ([ordered]@{exit_code=$exitCode;error=$failure;backup_directory=$BackupDirectory;completed_utc=[DateTime]::UtcNow.ToString('o')}) $ResultPath }
        catch { Write-Host ('Could not write elevation result: '+$_.Exception.Message) }
    }
    if (!$FromLauncher -and !$NoPause) { [void](Read-Host '按 Enter 关闭 / Press Enter to close') }
}
exit $exitCode
