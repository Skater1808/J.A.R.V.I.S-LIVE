# Jarvis — Launch Session (Windows)

# Load config
$configPath = Join-Path $PSScriptRoot "..\config.json"
$config = Get-Content $configPath | ConvertFrom-Json

$WORKSPACE_PATH = $config.workspace_path
$SPOTIFY_URI = $config.spotify_track
$BROWSER_URL = $config.browser_url

# Load assemblies
Add-Type -AssemblyName System.Windows.Forms
Add-Type @"
using System;
using System.Runtime.InteropServices;
public class WinPos {
    [DllImport("user32.dll")]
    public static extern bool MoveWindow(IntPtr hWnd, int X, int Y, int W, int H, bool repaint);
    [DllImport("user32.dll")]
    public static extern bool ShowWindow(IntPtr hWnd, int nCmdShow);
}
"@

function Snap-Window($proc, $x, $y, $w, $h) {
    if ($proc) {
        [WinPos]::ShowWindow($proc.MainWindowHandle, 9) | Out-Null
        Start-Sleep -Milliseconds 200
        [WinPos]::MoveWindow($proc.MainWindowHandle, $x, $y, $w, $h, $true) | Out-Null
    }
}

$screenW = [System.Windows.Forms.Screen]::PrimaryScreen.WorkingArea.Width
$screenH = [System.Windows.Forms.Screen]::PrimaryScreen.WorkingArea.Height
$halfW = [math]::Floor($screenW / 2)
$halfH = [math]::Floor($screenH / 2)

# 1. Start server FIRST - minimized to taskbar only
$serverCmd = "cd /d `"$WORKSPACE_PATH`" && python server.py"
Start-Process "cmd.exe" -ArgumentList "/k $serverCmd" -WindowStyle Minimized

# Give server time to start
Start-Sleep -Seconds 3

# Wait for server to be ready (port 8340)
$maxWait = 30
$portReady = $false
for ($i = 0; $i -lt $maxWait; $i++) {
    try {
        $tcp = New-Object System.Net.Sockets.TcpClient
        $tcp.Connect("localhost", 8340)
        $tcp.Close()
        Write-Host "[launch-session] Server ready on port 8340" -ForegroundColor Green
        $portReady = $true
        break
    } catch {
        Write-Host "[launch-session] Waiting for server... ($($i+1)/$maxWait)" -ForegroundColor Yellow
        Start-Sleep -Seconds 1
    }
}
if (-not $portReady) {
    Write-Host "[launch-session] Warning: Server not responding after 30s!" -ForegroundColor Red
    Write-Host "[launch-session] Check the server window for errors." -ForegroundColor Yellow
    Write-Host "[launch-session] Opening Chrome anyway..." -ForegroundColor Yellow
}

# 2. NOW open Chrome (server is running)
Start-Process "chrome" -ArgumentList "--autoplay-policy=no-user-gesture-required http://localhost:8340 $BROWSER_URL"

# 3. Start other apps
Start-Process $SPOTIFY_URI
# Note: VS Code is started via 'code' in config.apps - removed duplicate 'code $WORKSPACE_PATH'
foreach ($app in $config.apps) { Start-Process $app }

# 4. Snap all windows into quadrants
Start-Sleep -Seconds 3

$vscode = Get-Process -Name "Code" -ErrorAction SilentlyContinue | Where-Object { $_.MainWindowHandle -ne 0 } | Select-Object -First 1
Snap-Window $vscode 0 0 $halfW $halfH

$obsidian = Get-Process -Name "Obsidian" -ErrorAction SilentlyContinue | Where-Object { $_.MainWindowHandle -ne 0 } | Select-Object -First 1
Snap-Window $obsidian $halfW 0 $halfW $halfH

$chrome = Get-Process -Name "chrome" -ErrorAction SilentlyContinue | Where-Object { $_.MainWindowHandle -ne 0 } | Select-Object -First 1
Snap-Window $chrome 0 $halfH $halfW $halfH

$spotify = Get-Process -Name "Spotify" -ErrorAction SilentlyContinue | Where-Object { $_.MainWindowHandle -ne 0 } | Select-Object -First 1
Snap-Window $spotify $halfW $halfH $halfW $halfH
