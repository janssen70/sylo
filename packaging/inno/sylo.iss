; Sylo Windows installer (plan section 5).
;
; Authored on Linux -- there is no Windows machine or Wine/Inno Setup
; install in this dev environment, so this script has NOT been compiled or
; run. Build it with Inno Setup's ISCC on a Windows box (or under Wine)
; after producing the three exes via the .spec files in
; packaging/pyinstaller/:
;
;   pyinstaller packaging/pyinstaller/receiver.spec  --distpath dist --workpath build
;   pyinstaller packaging/pyinstaller/webapp.spec    --distpath dist --workpath build
;   pyinstaller packaging/pyinstaller/retention.spec --distpath dist --workpath build
;   iscc packaging/inno/sylo.iss
;
; Known gap, not solved here: if the admin password field below is left
; blank, sylo-webapp auto-generates one and logs it once via the `logging`
; module -- but a Windows service has no console, so today that log line
; goes nowhere visible. Until the webapp writes startup logs to a file or
; the Windows Event Log, installers should either type an explicit password
; here or be prepared to set SYLO_ADMIN_PASSWORD by hand and restart the
; service once to see the generated one.

#define MyAppName "Sylo"
#define MyAppVersion "0.1.0"
#define MyAppPublisher "Sylo"
; Fixed once and never changed across releases -- Inno uses this GUID (not
; the app name) to recognize "this is an upgrade of the same product."
#define MyAppId "{{0A55DFC6-FFEB-4AC1-8F72-626058010BB0}"
; Chosen after a real deployment found 8080 already in use by other software
; on the target machine -- see sylo/webapp/config.py for the port rationale.
; Kept in sync with WebConfig.port's own default by hand; there's no build
; step that shares a single source of truth between the two.
#define MyDefaultPort "8514"

[Setup]
AppId={#MyAppId}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion}
VersionInfoVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\Sylo
DefaultGroupName=Sylo
DisableProgramGroupPage=yes
; Installing/removing Windows services and writing to ProgramData both need
; admin rights; also the receiver binds privileged... no, actually UDP/TCP
; 514 needs no special Windows privilege (unlike Linux's CAP_NET_BIND_SERVICE
; requirement, see plan section 8) -- admin is needed here purely for the
; service-control and ProgramData-write operations below.
PrivilegesRequired=admin
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=..\..\dist\installer
OutputBaseFilename=sylo-setup
Compression=lzma
SolidCompression=yes
UninstallDisplayIcon={app}\sylo-webapp.exe

[Files]
; Each exe is a self-contained PyInstaller onefile build -- no separate
; Python/runtime install needed on the target machine (plan line 61).
Source: "..\..\dist\sylo-receiver.exe";  DestDir: "{app}"; Flags: ignoreversion
Source: "..\..\dist\sylo-webapp.exe";    DestDir: "{app}"; Flags: ignoreversion
Source: "..\..\dist\sylo-retention.exe"; DestDir: "{app}"; Flags: ignoreversion

[Dirs]
; Pre-created for visibility/permissions; the processes themselves also
; create these on demand (mkdir(parents=True, exist_ok=True) throughout),
; so this isn't load-bearing, just tidier for anyone poking around after
; install and before first service start.
Name: "{commonappdata}\Sylo\data\raw"
Name: "{commonappdata}\Sylo\data\index"

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop icon that opens Sylo in your browser"; GroupDescription: "Additional icons:"

[Icons]
; {group} still gets created even though DisableProgramGroupPage=yes just
; skips asking the user which group name to use -- it silently uses
; DefaultGroupName ("Sylo") instead. Without at least one Icons entry
; referencing {group}, no Start Menu folder would be created at all, which
; was the direct cause of the uninstaller having no easy-to-find entry point
; beyond Control Panel.
Name: "{group}\Sylo"; Filename: "{code:GetWebUrl}"; IconFilename: "{app}\sylo-webapp.exe"
Name: "{group}\Uninstall Sylo"; Filename: "{uninstallexe}"
Name: "{autodesktop}\Sylo"; Filename: "{code:GetWebUrl}"; Tasks: desktopicon; IconFilename: "{app}\sylo-webapp.exe"

[UninstallRun]
; Runs (in this order) before Inno deletes the app's files -- stop, then
; unregister, each service. skipifdoesntexist covers re-running an
; uninstall after a partial/failed install where a given service was never
; registered. RunOnceId matters beyond silencing the compiler warning: since
; this installer upgrades in place (fixed AppId, see MyAppId above), these
; [UninstallRun] entries also fire when re-running setup.exe over an
; existing install, not only from unins000.exe -- without RunOnceId, Inno
; has no record of "already ran for this exact entry" and could re-run a
; stop/remove pair on every maintenance/repeat install of the same version.
Filename: "{app}\sylo-receiver.exe";  Parameters: "stop";   Flags: runhidden waituntilterminated skipifdoesntexist; RunOnceId: "StopReceiver"
Filename: "{app}\sylo-receiver.exe";  Parameters: "remove"; Flags: runhidden waituntilterminated skipifdoesntexist; RunOnceId: "RemoveReceiver"
Filename: "{app}\sylo-webapp.exe";    Parameters: "stop";   Flags: runhidden waituntilterminated skipifdoesntexist; RunOnceId: "StopWebapp"
Filename: "{app}\sylo-webapp.exe";    Parameters: "remove"; Flags: runhidden waituntilterminated skipifdoesntexist; RunOnceId: "RemoveWebapp"
Filename: "{app}\sylo-retention.exe"; Parameters: "stop";   Flags: runhidden waituntilterminated skipifdoesntexist; RunOnceId: "StopRetention"
Filename: "{app}\sylo-retention.exe"; Parameters: "remove"; Flags: runhidden waituntilterminated skipifdoesntexist; RunOnceId: "RemoveRetention"

[Code]
var
  AdminPasswordPage: TInputQueryWizardPage;
  PortPage: TInputQueryWizardPage;

function DataRawDir(): String;
begin
  Result := ExpandConstant('{commonappdata}') + '\Sylo\data\raw';
end;

function DataIndexDir(): String;
begin
  Result := ExpandConstant('{commonappdata}') + '\Sylo\data\index';
end;

function AppDbPath(): String;
begin
  Result := ExpandConstant('{commonappdata}') + '\Sylo\data\app.sqlite3';
end;

procedure InitializeWizard();
begin
  AdminPasswordPage := CreateInputQueryPage(
    wpSelectDir,
    'Admin Account',
    'Choose a password for the default "admin" account',
    'Leave blank to auto-generate one instead (see the note at the top of ' +
    'this script for how to retrieve a generated password).'
  );
  AdminPasswordPage.Add('Password:', True);
  AdminPasswordPage.Add('Confirm password:', True);

  PortPage := CreateInputQueryPage(
    AdminPasswordPage.ID,
    'Web UI Port',
    'Choose the TCP port the Sylo web UI listens on',
    'Default is {#MyDefaultPort}. Change this only if that port is already ' +
    'in use by something else on this machine.'
  );
  PortPage.Add('Port:', False);
  PortPage.Values[0] := '{#MyDefaultPort}';
end;

function NextButtonClick(CurPageID: Integer): Boolean;
var
  PortNum: Integer;
begin
  Result := True;
  if CurPageID = AdminPasswordPage.ID then
  begin
    if AdminPasswordPage.Values[0] <> AdminPasswordPage.Values[1] then
    begin
      MsgBox('Passwords do not match.', mbError, MB_OK);
      Result := False;
    end;
  end
  else if CurPageID = PortPage.ID then
  begin
    PortNum := StrToIntDef(PortPage.Values[0], -1);
    if (PortNum < 1) or (PortNum > 65535) then
    begin
      MsgBox('Enter a valid port number (1-65535).', mbError, MB_OK);
      Result := False;
    end;
  end;
end;

// Used by the [Icons] entries above ({code:GetWebUrl}) for both the Start
// Menu and optional desktop shortcut -- one place computing the URL so the
// two shortcuts and the actual configured port can never drift apart.
function GetWebUrl(Param: String): String;
begin
  Result := 'http://127.0.0.1:' + PortPage.Values[0] + '/';
end;

// Registers a service (via that exe's own pywin32 install command), writes
// its per-service Environment values directly into the registry -- the
// documented way to give a Windows service env vars without polluting the
// system-wide environment or requiring a reboot for them to take effect --
// then starts it. Writing the registry key here (rather than declaratively
// in an [Registry] section, which runs before [Run]/before the service key
// even exists) keeps install-env-start in one guaranteed order.
// Two earlier attempts here (TArrayOfString, then array of String with a
// local-var copy) both hit "Type mismatch" on a real ISCC build -- turns out
// RegWriteMultiStringValue does not take an array at all, despite what its
// doc page's parameter name ("Data") suggests at a glance; its real
// signature is `Data: String`, a single string with each value joined by an
// embedded null character (#0), e.g. 'A' + #0 + 'B' + #0 + 'C'
// (confirmed against jrsoftware.org's own RegWriteMultiStringValue example).
// EnvLines stays a plain "array of String" open-array parameter -- fine for
// the caller side (CurStepChanged passes real dynamic arrays into it, which
// open-array parameters accept) -- and gets joined into EnvData below before
// the registry call, instead of being forwarded as an array anywhere.
procedure InstallService(ExeName, ServiceName: String; EnvLines: array of String);
var
  ResultCode, i: Integer;
  ExePath, EnvData: String;
begin
  ExePath := ExpandConstant('{app}') + '\' + ExeName;

  // Option before command, not after: pywin32's HandleCommandLine parses
  // argv with plain getopt.getopt (not gnu_getopt), which stops recognizing
  // "--startup=..." as an option once it hits the first non-option token --
  // so "install --startup=auto" leaves --startup=auto as a stray leftover
  // positional argument to the install command instead of being consumed as
  // the startup-type option (this was the actual cause of the "exited with
  // code 1" seen from inside the installer, even though a plain manual
  // `sylo-webapp.exe install` succeeds on its own).
  if not Exec(ExePath, '--startup=auto install', '', SW_HIDE, ewWaitUntilTerminated, ResultCode) then
    MsgBox('Failed to launch installer for ' + ServiceName + '.', mbError, MB_OK)
  else if ResultCode <> 0 then
    MsgBox(ServiceName + ' service registration exited with code ' + IntToStr(ResultCode) + '.', mbError, MB_OK);

  EnvData := '';
  for i := 0 to GetArrayLength(EnvLines) - 1 do
  begin
    if i > 0 then
      EnvData := EnvData + #0;
    EnvData := EnvData + EnvLines[i];
  end;

  // The service key already exists at this point (created by the install
  // step above); RegWriteMultiStringValue would create it if not, too.
  RegWriteMultiStringValue(HKLM, 'SYSTEM\CurrentControlSet\Services\' + ServiceName, 'Environment', EnvData);

  if not Exec(ExePath, 'start', '', SW_HIDE, ewWaitUntilTerminated, ResultCode) then
    MsgBox('Failed to launch ' + ServiceName + '.', mbError, MB_OK)
  else if ResultCode <> 0 then
    MsgBox(ServiceName + ' service start exited with code ' + IntToStr(ResultCode) + '.', mbError, MB_OK);
end;

procedure CurStepChanged(CurStep: TSetupStep);
var
  ReceiverEnv, WebappEnv, RetentionEnv: array of String;
  AdminPassword: String;
begin
  if CurStep = ssPostInstall then
  begin
    AdminPassword := AdminPasswordPage.Values[0];

    SetArrayLength(ReceiverEnv, 2);
    ReceiverEnv[0] := 'SYLO_DATA_DIR=' + DataRawDir();
    ReceiverEnv[1] := 'SYLO_INDEX_DIR=' + DataIndexDir();
    InstallService('sylo-receiver.exe', 'SyloReceiver', ReceiverEnv);

    if AdminPassword <> '' then
    begin
      SetArrayLength(WebappEnv, 4);
      WebappEnv[3] := 'SYLO_ADMIN_PASSWORD=' + AdminPassword;
    end
    else
      SetArrayLength(WebappEnv, 3);
    WebappEnv[0] := 'SYLO_APP_DB=' + AppDbPath();
    WebappEnv[1] := 'SYLO_INDEX_DIR=' + DataIndexDir();
    WebappEnv[2] := 'SYLO_WEB_PORT=' + PortPage.Values[0];
    InstallService('sylo-webapp.exe', 'SyloWebapp', WebappEnv);

    SetArrayLength(RetentionEnv, 3);
    RetentionEnv[0] := 'SYLO_DATA_DIR=' + DataRawDir();
    RetentionEnv[1] := 'SYLO_INDEX_DIR=' + DataIndexDir();
    RetentionEnv[2] := 'SYLO_APP_DB=' + AppDbPath();
    InstallService('sylo-retention.exe', 'SyloRetention', RetentionEnv);
  end;
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  // Data retained on uninstall unless the user opts out (plan line 60) --
  // IDYES ("keep") is the MsgBox's default button, so a hurried Enter-key
  // uninstall keeps data rather than deleting it.
  if CurUninstallStep = usPostUninstall then
  begin
    if MsgBox(
      'Keep the Sylo data directory (' + ExpandConstant('{commonappdata}') + '\Sylo) and its contents?' + #13#10 +
      'Choose No to permanently delete all recorded messages and settings.',
      mbConfirmation, MB_YESNO
    ) = IDNO then
      DelTree(ExpandConstant('{commonappdata}') + '\Sylo', True, True, True);
  end;
end;
