; Inno Setup 6 — Instalador LicitApp
; Requiere Inno Setup 6: https://jrsoftware.org/isinfo.php

[Setup]
AppName=LicitApp
AppVersion=2.6.0
AppPublisher=Poly Modules
AppPublisherURL=https://licitapp.co
AppSupportURL=mailto:polymodulospvc@gmail.com
AppUpdatesURL=https://licitapp.co/actualizar
DefaultDirName={autopf}\LicitApp
DefaultGroupName=LicitApp
AllowNoIcons=yes
OutputDir=..\dist\installer
OutputBaseFilename=LicitApp_Setup_v2.6
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
LicenseFile=..\LICENSE.txt
PrivilegesRequired=lowest
MinVersion=10.0
ArchitecturesAllowed=x64
ArchitecturesInstallIn64BitMode=x64

[Languages]
Name: "spanish"; MessagesFile: "compiler:Languages\Spanish.isl"

[Tasks]
Name: "desktopicon"; Description: "Crear acceso directo en el escritorio"; \
  GroupDescription: "Iconos adicionales:"
Name: "startupicon"; Description: "Iniciar LicitApp con Windows"; \
  GroupDescription: "Opciones de inicio:"; Flags: unchecked

[Files]
Source: "..\dist\LicitApp\*"; DestDir: "{app}"; \
  Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\LicitApp"; \
  Filename: "{app}\LicitApp.exe"; \
  Comment: "Plataforma de LicitApp — Licitaciones Colombia"
Name: "{group}\Desinstalar LicitApp"; \
  Filename: "{uninstallexe}"
Name: "{autodesktop}\LicitApp"; \
  Filename: "{app}\LicitApp.exe"; \
  Tasks: desktopicon; \
  Comment: "Plataforma de LicitApp — Licitaciones Colombia"

[Registry]
Root: HKCU; \
  Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; \
  ValueType: string; ValueName: "SECOPAutomatizador"; \
  ValueData: """{app}\LicitApp.exe"""; \
  Flags: uninsdeletevalue; Tasks: startupicon

[Run]
Filename: "{app}\LicitApp.exe"; \
  Description: "Abrir LicitApp ahora"; \
  Flags: nowait postinstall skipifsilent

[UninstallDelete]
Type: filesandordirs; Name: "{app}\logs"

[Code]
procedure InitializeWizard();
begin
  WizardForm.WelcomeLabel2.Caption :=
    'Este asistente instalara LicitApp en tu computador.' + Chr(13) + Chr(10) +
    Chr(13) + Chr(10) +
    'LicitApp: plataforma para gestionar y ganar licitaciones publicas en Colombia (SECOP I y II).' +
    Chr(13) + Chr(10) + Chr(13) + Chr(10) +
    'Se recomienda cerrar todas las aplicaciones antes de continuar.';
end;
