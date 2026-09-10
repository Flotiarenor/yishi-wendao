# 一世问道 · 桌面壳启动器（Windows）
#
# 生成一个带 AppUserModelID 的快捷方式：
#   AppUserModelID = YishiWendao.Xiuxian   ← 任务栏分组/固定/通知都靠它
#   目标 = .venv\Scripts\pythonw.exe        ← pythonw 无控制台窗口（python 会弹黑框）
#   工作目录 = 仓库根，参数 = main.py app
#
# 为什么要快捷方式而不是直接跑 pythonw：
#   直接双击 .pyw 会被 Windows 归到 python 名下（任务栏变 python 图标、
#   固定到任务栏也分组到 python）。快捷方式能显式带上 AppUserModelID 与图标。
#
# ⚠️ 音量合成器里仍会显示「Microsoft Edge WebView2」——那是 WebView2 的限制，
#    与快捷方式无关（详见 server/desktop.py 顶部说明）。
#
# 用法：
#   powershell -ExecutionPolicy Bypass -File tools\make_shortcut.ps1
#   （默认在桌面生成「一世问道.lnk」；可用 -OutDir 指定别处）

param(
    [string]$OutDir = [Environment]::GetFolderPath('Desktop'),
    [string]$Name = '一世问道'
)

$ErrorActionPreference = 'Stop'

# 仓库根 = 本脚本的上上级
$root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$pythonw = Join-Path $root '.venv\Scripts\pythonw.exe'
$icon = Join-Path $root 'assets\app.ico'

if (-not (Test-Path $pythonw)) {
    Write-Warning "找不到 $pythonw —— 回退到 python.exe（会有控制台窗口）"
    $pythonw = Join-Path $root '.venv\Scripts\python.exe'
}
if (-not (Test-Path $icon)) { Write-Warning "找不到图标 $icon（快捷方式会用默认图标）" }
if (-not (Test-Path $OutDir)) { New-Item -ItemType Directory -Force -Path $OutDir | Out-Null }

$lnkPath = Join-Path $OutDir "$Name.lnk"
$shell = New-Object -ComObject WScript.Shell
$lnk = $shell.CreateShortcut($lnkPath)
$lnk.TargetPath = $pythonw
$lnk.Arguments = "`"$root\main.py`" app"
$lnk.WorkingDirectory = $root
if (Test-Path $icon) { $lnk.IconLocation = "$icon,0" }
$lnk.Description = '一世问道 · 文字修仙（桌面壳）'
$lnk.Save()

# 关键一步：把 AppUserModelID 写进快捷方式，任务栏才会认成"我们的应用"。
# 用 COM（IShellLink + IPropertyStore）——`Add-Type -MemberDefinition` 在
# Windows PowerShell 5.1 里装不下这么多类型，必须用 -TypeDefinition 编译。
$cs = @'
using System;
using System.Runtime.InteropServices;
using System.Text;

public static class YwShortcut {
    [DllImport("shell32.dll", CharSet = CharSet.Unicode)]
    public static extern int SetCurrentProcessExplicitAppUserModelID(string appId);

    [ComImport, Guid("00021401-0000-0000-C000-000000000046")]
    internal class ShellLink { }

    [ComImport, Guid("000214F9-0000-0000-C000-000000000046"),
     InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
    internal interface IShellLinkW {
        void GetPath([MarshalAs(UnmanagedType.LPWStr)] StringBuilder pszFile, int cch, IntPtr pfd, int fFlags);
        void GetIDList(out IntPtr ppidl);
        void SetIDList(IntPtr pidl);
        void GetDescription([MarshalAs(UnmanagedType.LPWStr)] StringBuilder pszName, int cch);
        void SetDescription([MarshalAs(UnmanagedType.LPWStr)] string pszName);
        void GetWorkingDirectory([MarshalAs(UnmanagedType.LPWStr)] StringBuilder pszDir, int cch);
        void SetWorkingDirectory([MarshalAs(UnmanagedType.LPWStr)] string pszDir);
        void GetArguments([MarshalAs(UnmanagedType.LPWStr)] StringBuilder pszArgs, int cch);
        void SetArguments([MarshalAs(UnmanagedType.LPWStr)] string pszArgs);
        void GetHotkey(out short pwHotkey);
        void SetHotkey(short wHotkey);
        void GetShowCmd(out int piShowCmd);
        void SetShowCmd(int iShowCmd);
        void GetIconLocation([MarshalAs(UnmanagedType.LPWStr)] StringBuilder pszIconPath, int cch, out int piIcon);
        void SetIconLocation([MarshalAs(UnmanagedType.LPWStr)] string pszIconPath, int iIcon);
        void SetRelativePath([MarshalAs(UnmanagedType.LPWStr)] string pszPathRel, int dwReserved);
        void Resolve(IntPtr hwnd, int fFlags);
        void SetPath([MarshalAs(UnmanagedType.LPWStr)] string pszFile);
    }

    [ComImport, Guid("0000010b-0000-0000-C000-000000000046"),
     InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
    internal interface IPersistFile {
        void GetClassID(out Guid pClassID);
        [PreserveSig] int IsDirty();
        void Load([MarshalAs(UnmanagedType.LPWStr)] string pszFileName, int dwMode);
        void Save([MarshalAs(UnmanagedType.LPWStr)] string pszFileName, bool fRemember);
        void SaveCompleted([MarshalAs(UnmanagedType.LPWStr)] string pszFileName);
        void GetCurFile([MarshalAs(UnmanagedType.LPWStr)] StringBuilder ppszFileName);
    }

    [StructLayout(LayoutKind.Sequential, Pack = 4)]
    internal struct PROPERTYKEY { public Guid fmtid; public uint pid; }

    [StructLayout(LayoutKind.Explicit)]
    internal struct PROPVARIANT {
        [FieldOffset(0)] public ushort vt;
        [FieldOffset(8)] public IntPtr pointerValue;
    }

    [ComImport, Guid("886D8EEB-8CF2-4446-8D02-CDBA1DBDCF99"),
     InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
    internal interface IPropertyStore {
        void GetCount(out uint cProps);
        void GetAt(uint iProp, out PROPERTYKEY pkey);
        void GetValue(ref PROPERTYKEY key, out PROPVARIANT pv);
        void SetValue(ref PROPERTYKEY key, ref PROPVARIANT pv);
        void Commit();
    }

    // 给 .lnk 写入 System.AppUserModel.ID（任务栏分组 / 固定 / 通知都靠它）
    public static void SetLnkAppUserModelId(string lnkPath, string appId) {
        var link = (IShellLinkW)new ShellLink();
        var pf = (IPersistFile)link;
        pf.Load(lnkPath, 2);                        // STGM_READWRITE
        var ps = (IPropertyStore)link;
        var key = new PROPERTYKEY();
        key.fmtid = new Guid("9F4C2855-9F79-4B39-A8D0-E1D42DE1D5F3");
        key.pid = 5;                                // System.AppUserModel.ID
        var pv = new PROPVARIANT();
        pv.vt = 31;                                 // VT_LPWSTR
        pv.pointerValue = Marshal.StringToCoTaskMemUni(appId);
        try {
            ps.SetValue(ref key, ref pv);
            ps.Commit();
        } finally {
            Marshal.FreeCoTaskMem(pv.pointerValue);
        }
        pf.Save(lnkPath, true);
    }
}
'@

$aumid = 'YishiWendao.Xiuxian'
Add-Type -TypeDefinition $cs -Language CSharp
try {
    [YwShortcut]::SetLnkAppUserModelId($lnkPath, $aumid)
    Write-Host "已写入 AppUserModelID: $aumid"
} catch {
    Write-Warning "写入 AppUserModelID 失败：$($_.Exception.Message)"
    Write-Warning "任务栏会按 python 分组；不影响游戏运行。"
}

Write-Host ""
Write-Host "已生成：$lnkPath"
Write-Host "  目标：`"$pythonw`" `"$root\main.py`" app"
Write-Host "  图标：$icon"
Write-Host "  AppUserModelID：$aumid"
