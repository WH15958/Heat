; All paths and version are provided by build_desktop.ps1.
#ifndef BuildRoot
  #error BuildRoot is required
#endif
#ifndef WebView2Installer
  #error WebView2Installer is required
#endif
#ifndef AppVersion
  #define AppVersion "0.1.5"
#endif

[Setup]
AppId={{9E1CC18A-6502-47A1-BF7E-53887503E478}
AppName=Heat
AppVersion={#AppVersion}
AppPublisher=Heat
DefaultDirName={localappdata}\Programs\Heat
PrivilegesRequired=lowest
ArchitecturesAllowed=x64os
ArchitecturesInstallIn64BitMode=x64os
MinVersion=10.0.22000
DefaultGroupName=Heat
DisableProgramGroupPage=yes
DisableDirPage=yes
OutputDir={#BuildRoot}\release
OutputBaseFilename=Heat-Setup-{#AppVersion}-x64
SetupIconFile={#BuildRoot}\assets\heat.ico
UninstallDisplayIcon={app}\Heat.exe
Compression=lzma2
SolidCompression=yes
AppMutex=HeatDesktopShell,HeatDesktopBackend
CloseApplications=no
RestartApplications=no
Uninstallable=yes
WizardStyle=modern

[Files]
Source: "{#BuildRoot}\dist\Heat\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "{#WebView2Installer}"; Flags: dontcopy

[Icons]
Name: "{autoprograms}\Heat"; Filename: "{app}\Heat.exe"; WorkingDir: "{app}"
Name: "{autodesktop}\Heat"; Filename: "{app}\Heat.exe"; WorkingDir: "{app}"

[Code]
const
  WebViewKey = 'Software\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}';

function HeatRunning(): Boolean;
begin
  Result := CheckForMutexes('HeatDesktopShell,HeatDesktopBackend');
end;

function InitializeSetup(): Boolean;
begin
  Result := not HeatRunning();
  if not Result then
    MsgBox('Heat is running. Use Exit Heat and wait for the backend to stop before installing or upgrading.', mbError, MB_OK);
end;

function InitializeUninstall(): Boolean;
begin
  Result := not HeatRunning();
  if not Result then
    MsgBox('Heat is running. Use Exit Heat and wait for the backend to stop before uninstalling.', mbError, MB_OK);
end;

function RuntimeInHive(RootKey: Integer): Boolean;
var
  Version: String;
begin
  Result := RegQueryStringValue(RootKey, WebViewKey, 'pv', Version) and
    (Version <> '') and (Version <> '0.0.0.0');
end;

function WebView2Installed(): Boolean;
begin
  Result := RuntimeInHive(HKCU32) or RuntimeInHive(HKCU64) or
    RuntimeInHive(HKLM32) or RuntimeInHive(HKLM64);
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
var
  ExitCode: Integer;
  InstallerPath: String;
begin
  Result := '';
  if HeatRunning() then begin
    Result := 'Heat started while setup was open. Exit Heat normally, then retry.';
    exit;
  end;
  if WebView2Installed() then exit;
  ExtractTemporaryFile('MicrosoftEdgeWebView2RuntimeInstallerX64.exe');
  InstallerPath := ExpandConstant('{tmp}\MicrosoftEdgeWebView2RuntimeInstallerX64.exe');
  if not Exec(InstallerPath, '/silent /install', '', SW_HIDE, ewWaitUntilTerminated, ExitCode) then begin
    Result := 'The bundled offline Microsoft WebView2 installer could not start.';
    exit;
  end;
  if (ExitCode <> 0) and (ExitCode <> 3010) then begin
    Result := 'Offline Microsoft WebView2 installation failed (exit code ' + IntToStr(ExitCode) + ').';
    exit;
  end;
  if not WebView2Installed() then begin
    Result := 'Microsoft WebView2 was not detected after offline installation. Setup cannot continue.';
    exit;
  end;
  NeedsRestart := ExitCode = 3010;
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  if (CurUninstallStep = usUninstall) and HeatRunning() then
    RaiseException('Heat is running. Exit Heat normally before uninstalling.');
end;

// No UninstallDelete entry: user data under LocalAppData\Heat is always retained.
