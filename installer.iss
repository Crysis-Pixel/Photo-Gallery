; Inno Setup script for Photo Gallery
; This script packages the 2.7 GB GPU-enabled Photo Gallery sidecar and app executables.

#define MyAppName "Photo Gallery"
#define MyAppVersion "0.1.0"
#define MyAppPublisher "Belford Blaze"
#define MyAppExeName "app.exe"
#define MyBackendExeName "photo-gallery-backend.exe"

[Setup]
AppId={{D1A39C29-798B-4DC0-9EE6-3829FE7F95A1}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\{#MyAppName}
DisableProgramGroupPage=yes
SetupIconFile=frontend\src-tauri\icons\icon.ico
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
UninstallDisplayIcon={app}\{#MyAppExeName}
OutputBaseFilename=Photo-Gallery-Setup-{#MyAppVersion}
OutputDir=frontend\src-tauri\target\release\bundle\inno
CloseApplications=yes
AppMutex=com.belfordblaze.photo-gallery

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
Source: "frontend\src-tauri\target\release\app.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "frontend\src-tauri\target\release\photo-gallery-backend.exe"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{autoprograms}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(MyAppName, '&', '&&')}}"; Flags: nowait postinstall skipifsilent

[Code]
function InitializeSetup(): Boolean;
var
  ResultCode: Integer;
begin
  Result := True;
  // Force terminate any running processes to prevent file locking
  ShellExec('open', 'taskkill.exe', '/f /im app.exe', '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
  ShellExec('open', 'taskkill.exe', '/f /im photo-gallery-backend.exe', '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
end;

function InitializeUninstall(): Boolean;
var
  ResultCode: Integer;
begin
  Result := True;
  // Force terminate any running processes to prevent file locking during uninstallation
  ShellExec('open', 'taskkill.exe', '/f /im app.exe', '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
  ShellExec('open', 'taskkill.exe', '/f /im photo-gallery-backend.exe', '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
end;

procedure CurUninstallStepChanged(JustAfterAnUninstallStep: TUninstallStep);
begin
  if JustAfterAnUninstallStep = usPostUninstall then
  begin
    if MsgBox('Do you want to delete your local photo database and cached thumbnails?', mbConfirmation, MB_YESNO) = IDYES then
    begin
      DelTree(ExpandConstant('{app}\thumbnails'), True, True, True);
      DeleteFile(ExpandConstant('{app}\gallery.db'));
      DeleteFile(ExpandConstant('{app}\gallery.db-wal'));
      DeleteFile(ExpandConstant('{app}\gallery.db-shm'));
      // Clean up empty installation folder
      RemoveDir(ExpandConstant('{app}'));
    end;
  end;
end;
