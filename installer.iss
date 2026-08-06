; SloppyKeys installer (Inno Setup 6.3+ — `x64compatible` needs 6.3). Build the folder
; first, then compile this:
;
;   .venv\Scripts\python.exe build_exe.py
;   "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe" installer.iss
;
; That is where `winget install JRSoftware.InnoSetup` puts it without elevation — a
; per-user install, so it is not under Program Files.
;
; Output: installer_output\SloppyKeys-Setup-beta.exe
;
; # Where the user's data lives
; In the install folder, beside the exe: `images\`, `configs\`, `routes.json`,
; `settings.json`, `log.txt`. That is not a choice the installer makes —
; `window.resolve_app_root()` returns the exe's own directory when frozen, so the install
; folder *is* the data folder, and a zip copy of the same build behaves identically.
;
; # Why a per-user install, not Program Files
; Because of the above, the install folder must stay writable by the user who runs the app.
; Program Files is not, so an install there would need admin rights for every capture.
; `{localappdata}\Programs` is writable, needs no UAC prompt, and is what VS Code and
; Discord do for the same reason. `CheckWritableDir` warns if the user redirects the
; install somewhere unwritable, because the app fails *quietly* there: a capture that
; can't be saved looks like a capture that didn't work.
;
; # Why user data is never overwritten, and never uninstalled
; Every data file is `onlyifdoesntexist` + `uninsneveruninstall`:
;   - `onlyifdoesntexist` — a user who recaptured a template for their own screen must not
;     have it replaced by the shipped one on the next upgrade. New files still arrive,
;     because the flag is per file. This also makes a **reinstall act as a repair**: any
;     shipped file the user deleted comes back, anything they changed is left alone.
;   - `uninsneveruninstall` — without it, uninstall deletes every path setup once wrote,
;     including the ones whose contents are now the user's own recapture or unit plan.
;     Instead `CurUninstallStepChanged` *asks* before removing the data.
;
; # What is not here
; AutoHotkey v2. See the note by `InitializeSetup`.

#define AppName "SloppyKeys"
; Deliberately a word, not a number — matches `ui/window.py::VERSION`. There is no release
; cadence to track yet, and a stale version is worse than none.
#define AppVersion "beta"
#define AppExe "SloppyKeys.exe"
; Where build_exe.py put the runnable folder (relative to this file).
#define Payload "..\..\SLOPPYKEYS"

[Setup]
; A real GUID. Never change it after a public release — it is how an upgrade finds the
; existing install instead of orphaning it.
AppId={{8E5C6E2A-4B7D-4C1E-9A3F-51099AC5E401}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher=SloppyKeys
DefaultDirName={localappdata}\Programs\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
; Per-user: no admin, and the install folder stays writable so captures work.
PrivilegesRequired=lowest
OutputDir=installer_output
OutputBaseFilename={#AppName}-Setup-{#AppVersion}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
UninstallDisplayIcon={app}\{#AppExe}

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Shortcuts:"

[Files]
; The program. Replaced on every upgrade, removed on uninstall.
Source: "{#Payload}\{#AppExe}"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#Payload}\_internal\*"; DestDir: "{app}\_internal"; Flags: ignoreversion recursesubdirs createallsubdirs

; User data — see the note at the top for both flags. `skipifsourcedoesntexist` because a
; build with no routes yet is legitimate.
Source: "{#Payload}\images\*"; DestDir: "{app}\images"; Flags: onlyifdoesntexist uninsneveruninstall recursesubdirs createallsubdirs skipifsourcedoesntexist
Source: "{#Payload}\configs\*"; DestDir: "{app}\configs"; Flags: onlyifdoesntexist uninsneveruninstall recursesubdirs createallsubdirs skipifsourcedoesntexist
Source: "{#Payload}\routes.json"; DestDir: "{app}"; Flags: onlyifdoesntexist uninsneveruninstall skipifsourcedoesntexist
Source: "{#Payload}\settings.json"; DestDir: "{app}"; Flags: onlyifdoesntexist uninsneveruninstall skipifsourcedoesntexist

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{userdesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExe}"; Description: "Launch {#AppName}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; Written at runtime, so Inno doesn't know about them and would leave them behind. These
; are logs, not data — removed without asking.
Type: files; Name: "{app}\log.txt"
Type: files; Name: "{app}\log.prev.txt"
Type: files; Name: "{app}\crash.txt"

[Code]
// AutoHotkey v2 is a separate program the macro shells out to (core\ahk.py). It cannot be
// bundled — it is GPL and it is an installer, not a file to copy — so the honest thing is
// to say so before the user finds out by every click failing. A warning, not a blocker:
// they may be installing this ahead of AHK deliberately.
function AhkInstalled(): Boolean;
begin
  Result := FileExists(ExpandConstant('{pf}\AutoHotkey\v2\AutoHotkey64.exe'))
         or FileExists(ExpandConstant('{pf}\AutoHotkey\v2\AutoHotkey32.exe'))
         or FileExists(ExpandConstant('{pf}\AutoHotkey\v2\AutoHotkey.exe'));
end;

function InitializeSetup(): Boolean;
begin
  Result := True;
  if not AhkInstalled() then
    MsgBox('AutoHotkey v2 was not found.' + #13#10#13#10 +
           'SloppyKeys sends every click and keypress through it, so the macro cannot ' +
           'drive the game until it is installed. Get it from autohotkey.com — the v2 ' +
           'release, not v1.' + #13#10#13#10 +
           'You can finish this install now and add AutoHotkey afterwards.',
           mbInformation, MB_OK);
end;

// The app stores its data in the install folder, so an unwritable target breaks captures,
// unit plans and the log — and breaks them *silently*. Test by writing, not by inspecting
// the path: virtualisation and redirected folders make a path check a guess.
function CheckWritableDir(Dir: String): Boolean;
var
  Probe: String;
begin
  Probe := AddBackslash(Dir) + 'sloppykeys_write_test.tmp';
  Result := ForceDirectories(Dir) and SaveStringToFile(Probe, 'x', False);
  if Result then
    DeleteFile(Probe);
end;

function NextButtonClick(CurPageID: Integer): Boolean;
begin
  Result := True;
  if CurPageID <> wpSelectDir then
    Exit;
  if CheckWritableDir(WizardDirValue) then
    Exit;
  Result := MsgBox('SloppyKeys cannot write to that folder.' + #13#10#13#10 +
                   'It keeps your captured templates, unit plans and settings next to the ' +
                   'program, so a read-only location (Program Files, for example) means ' +
                   'nothing you set up will be saved.' + #13#10#13#10 +
                   'Install there anyway?', mbError, MB_YESNO) = IDYES;
end;

// Data survives uninstall by default (`uninsneveruninstall`), so this is the only way it
// ever gets removed — and only when the user says so. Losing 41 hand-picked unit plans to
// an uninstall-then-reinstall is not a trade worth making silently.
procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  if CurUninstallStep <> usPostUninstall then
    Exit;
  if UninstallSilent then
    Exit;
  // Never start a continuation line with `#13` — the preprocessor reads a leading `#` as
  // a directive and aborts the compile. Keep the linebreaks trailing.
  if MsgBox('Also delete your SloppyKeys data?' + #13#10#13#10 +
            'That is your captured templates (images), unit plans (configs), Events ' +
            'routes, and settings including the private server link and Discord ' +
            'webhook.' + #13#10#13#10 +
            'Choose No to keep them for a future reinstall.',
            mbConfirmation, MB_YESNO) <> IDYES then
    Exit;
  DelTree(ExpandConstant('{app}\images'), True, True, True);
  DelTree(ExpandConstant('{app}\configs'), True, True, True);
  DeleteFile(ExpandConstant('{app}\routes.json'));
  DeleteFile(ExpandConstant('{app}\settings.json'));
  DelTree(ExpandConstant('{app}'), True, True, True);
end;
