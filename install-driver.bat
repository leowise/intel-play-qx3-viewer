@echo off
setlocal EnableExtensions
title Intel Play QX3 - USB Driver Setup
cd /d "%~dp0"

net session >nul 2>&1
if %errorLevel% neq 0 (
    echo Administrator permission is required to install the USB driver.
    echo Click Yes on the Windows prompt.
    powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
    exit /b
)

powershell -NoProfile -ExecutionPolicy Bypass -Command "$p='%~f0'; $Root=[IO.Path]::GetDirectoryName($p); $l=Get-Content -LiteralPath $p; $i=0; while($i -lt $l.Count -and $l[$i] -ne ':::PS'){$i++}; Invoke-Expression (($l[($i+1)..($l.Count-1)]) -join [char]10)"
set ERR=%ERRORLEVEL%
echo.
pause
exit /b %ERR%

:::PS
$ErrorActionPreference = "Stop"
$Inf  = Join-Path $Root "drivers\qx3_winusb.inf"
$HwId = "USB\VID_0813&PID_0001"

Write-Host "============================================"
Write-Host " Intel Play QX3 - automatic WinUSB setup"
Write-Host "============================================"
Write-Host ""

$infText = @'
[Version]
Signature   = "$WINDOWS NT$"
Class       = USBDevice
ClassGuid   = {88BAE032-5A81-49f0-BC3D-A4FF138216D6}
Provider    = %ManufacturerName%
DriverVer   = 08/25/2026,1.0.0.0
PnpLockdown = 1

[Manufacturer]
%ManufacturerName% = Standard,NTamd64

[Standard.NTamd64]
%DeviceName% = USB_Install, USB\VID_0813&PID_0001

[USB_Install]
Include = winusb.inf
Needs   = WINUSB.NT

[USB_Install.Services]
Include = winusb.inf
Needs   = WINUSB.NT.Services

[USB_Install.HW]
AddReg = USB_AddReg

[USB_AddReg]
HKR,,DeviceInterfaceGUIDs,0x00010000,"{88BAE032-5A81-49f0-BC3D-A4FF138216D6}"

[Strings]
ManufacturerName = "Intel Play QX3 Open Source"
DeviceName = "Intel Play QX3 Microscope"
'@

if (-not (Test-Path $Inf)) {
    $Inf = Join-Path $env:TEMP "qx3_winusb.inf"
    Set-Content -LiteralPath $Inf -Value $infText -Encoding ASCII
}

function Get-Qx3Device {
    Get-PnpDevice -ErrorAction SilentlyContinue |
        Where-Object { $_.InstanceId -like "*VID_0813&PID_0001*" }
}

Write-Host "Looking for the microscope (USB 0813:0001)..."
$dev = Get-Qx3Device
if (-not $dev) {
    Write-Host "Plug the microscope into a USB port now."
    Write-Host "Waiting up to 45 seconds..."
    $deadline = (Get-Date).AddSeconds(45)
    while (-not $dev -and (Get-Date) -lt $deadline) {
        Start-Sleep -Seconds 2
        $dev = Get-Qx3Device
    }
}

if ($dev) {
    Write-Host ("Found: {0}" -f ($dev | Select-Object -First 1 | ForEach-Object { "$($_.FriendlyName)  [$($_.Status)] $($_.InstanceId)" }))
} else {
    Write-Host "WARNING: Device not visible yet. The driver will still be bound to 0813:0001."
    Write-Host "         Plug it in before you run run.bat."
}
Write-Host ""

$already = $dev | Where-Object { $_.Service -eq "WINUSB" -or $_.Service -eq "WinUSB" }
if ($already) {
    Write-Host "WinUSB is already installed for this microscope."
    Write-Host "You can close this window and double-click run.bat"
    exit 0
}

Add-Type -TypeDefinition @"
using System;
using System.Runtime.InteropServices;
public static class Qx3Driver {
    public const uint INSTALLFLAG_FORCE = 0x00000001;
    [DllImport("newdev.dll", CharSet = CharSet.Unicode, SetLastError = true)]
    public static extern bool UpdateDriverForPlugAndPlayDevices(
        IntPtr hwndParent, string HardwareId, string FullInfPath, uint InstallFlags, out bool RebootRequired);
    [DllImport("newdev.dll", CharSet = CharSet.Unicode, SetLastError = true)]
    public static extern bool DiInstallDriver(
        IntPtr hwndParent, string InfPath, uint Flags, out bool RebootRequired);
}
"@

$infFull = (Resolve-Path $Inf).Path
$reboot = $false
$ok = $false

Write-Host "Installing Microsoft WinUSB for $HwId ..."
try {
    $ok = [Qx3Driver]::UpdateDriverForPlugAndPlayDevices(
        [IntPtr]::Zero, $HwId, $infFull,
        [Qx3Driver]::INSTALLFLAG_FORCE, [ref]$reboot)
} catch {
    $ok = $false
}

if (-not $ok) {
    Write-Host "Primary bind did not finish. Trying the driver store..."
    $pnp = Start-Process -FilePath "pnputil.exe" -ArgumentList @("/add-driver", $infFull, "/install") -Wait -PassThru -NoNewWindow
    if ($pnp.ExitCode -eq 0) { $ok = $true }
}

if (-not $ok) {
    try {
        $ok = [Qx3Driver]::DiInstallDriver([IntPtr]::Zero, $infFull, 0, [ref]$reboot)
    } catch {
        $ok = $false
    }
}

Start-Sleep -Seconds 2
$dev = Get-Qx3Device
$winusb = $false
if ($dev) {
    $svc = ($dev | Select-Object -First 1).Service
    if ($svc -eq "WinUSB" -or $svc -eq "WINUSB") { $winusb = $true }
    Write-Host ("Driver service now: {0}" -f $svc)
}

if ($ok -or $winusb) {
    Write-Host ""
    Write-Host "Done. WinUSB is ready."
    if ($reboot) {
        Write-Host "Windows asked for a reboot. Reboot if the viewer cannot see the camera."
    }
    Write-Host "Next: double-click run.bat"
    exit 0
}

$err = [Runtime.InteropServices.Marshal]::GetLastWin32Error()
Write-Host ""
Write-Host "Automatic install did not complete (Win32 error $err)."
Write-Host "Downloading Zadig as a backup..."
$zadig = Join-Path $env:TEMP "zadig-2.9.exe"
try {
    [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
    Invoke-WebRequest -Uri "https://github.com/pbatard/libwdi/releases/download/v1.5.1/zadig-2.9.exe" -OutFile $zadig -UseBasicParsing
    Write-Host "Starting Zadig. Select the QX3 (0813:0001), choose WinUSB, click Install Driver."
    Start-Process $zadig
} catch {
    Write-Host "Could not download Zadig. Open https://zadig.akeo.ie/ and install WinUSB for 0813:0001."
    Start-Process "https://zadig.akeo.ie/"
    exit 1
}
exit 1
