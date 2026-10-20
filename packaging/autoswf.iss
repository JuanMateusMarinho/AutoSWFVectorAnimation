; packaging/autoswf.iss: the per-user AutoSWF installer (Inno Setup 6). packaging/build.py compiles it after the
; PyInstaller build:  ISCC /DAppVersion=0.1.0 /DDistDir=<dist> packaging\autoswf.iss
; The AQW files the app downloads on first run live in %LOCALAPPDATA%\AutoSWF and are never removed by the uninstaller.

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif
#ifndef DistDir
  #define DistDir "..\dist"
#endif

[Setup]
AppId={{6C1F3B52-8E2A-4D6B-9A47-3F0E5B9D2C81}
AppName=AutoSWF
AppVersion={#AppVersion}
AppPublisher=Juan Mateus Marinho
DefaultDirName={localappdata}\Programs\AutoSWF
DefaultGroupName=AutoSWF
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir={#DistDir}
OutputBaseFilename=AutoSWF-Setup-{#AppVersion}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
UninstallDisplayIcon={app}\AutoSWF.exe
UninstallDisplayName=AutoSWF

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
Source: "{#DistDir}\AutoSWF\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\AutoSWF"; Filename: "{app}\AutoSWF.exe"
Name: "{autodesktop}\AutoSWF"; Filename: "{app}\AutoSWF.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\AutoSWF.exe"; Description: "{cm:LaunchProgram,AutoSWF}"; Flags: nowait postinstall skipifsilent

[Code]
procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  if (CurUninstallStep = usPostUninstall) and not UninstallSilent() then
    MsgBox('The AQW files AutoSWF downloaded are kept in ' + ExpandConstant('{localappdata}\AutoSWF') +
           '. Delete that folder to remove them too.', mbInformation, MB_OK);
end;
