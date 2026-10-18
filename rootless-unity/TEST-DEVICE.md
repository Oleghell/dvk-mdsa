# Rootless Gadget test tool 0.1.0 — only MuMu #4

Experimental test installer + fixed metadata probe, not production app automation.
No root, OCR, screenshots, profile/chat reads, coordinate taps, message sending,
login transfer, paid actions or protection bypass. No MCP/HTTP server or tunnel.

## User steps

1. Start **both** MuMu instances: working #0 at `127.0.0.1:5555` and test #4 at `127.0.0.1:5563`.
2. Extract the **private** supplied test bundle outside the ZIP. Do not drag the APKs into the working emulator.
3. Run `Dvk-rootless-test.exe`; choose trusted `adb.exe` / `adb_server.exe` from MuMu if not found.
4. Leave/select the bundle's `test-apks` folder, check the consent box for #4 only.
5. Click **Установить и проверить на #4**. Do not log in to a personal account for this initial load test.
6. Attach `rootless-test-result.json` from next to `test-apks` to the private chat.

The public GitHub release contains **only the tool**, not app APKs or signing keys.
An actual installation requires the separately supplied private bundle.
If Windows blocks execution, do not disable antivirus/security protections; report the warning.

## Guards

- Target is hardcoded to `127.0.0.1:5563`; the tool cannot install on 5555 or change target ports.
- Both devices must be online. Their kernel boot IDs must be valid and different, and are
  rechecked before installation/launch. IDs remain in memory and never enter the report.
- If boot IDs cannot be read, fail closed. Do not grant root/change system permissions.
- If `drug.vokrug` already exists on #4, installation stops. No `-r`, uninstall, clear-data,
  force-stop, re-sign/update-in-place, automatic retries or rollback removal.
- On a previous successful test installation, manually open that test app on #4 and use
  **Только проверка Gadget**; this button neither installs nor starts the app.
- Only the exact audited private test APK pair passes SHA-256 checks. Signature mismatch,
  missing files, ports pointing to the same Android, or a device restart stops work.
- ADB commands use a finite allowlist, argument arrays and `shell=False` on the host.
  Only boot-ID/get-state reads and connection are allowed for the working device.
- A fresh loopback host port is forwarded only to test Gadget `tcp:27042`, authenticated
  with its local APK token. The tool removes only the forward it created, not other forwards.
  Failed cleanup is recorded in the report. There is no public listening interface.

## Probe scope and limitations

Frida 17.24.1 runs **one fixed script** checking architecture/version and loaded
`libunity.so` / `libil2cpp.so` plus four named IL2CPP exports. It does not invoke native
app functions, inspect object fields, intercept functions, or read profiles/messages.
The tool does not accept arbitrary JavaScript or expose RPC over MCP.
A successful probe proves only Gadget/module availability, **not Unity UI-object access**.
Module-loaded/exports-present is not proof that a full workflow works.

If installation succeeds but startup/probing fails, the test copy stays on #4.
Cancellation is not an uninstall and takes effect after the current bounded ADB command.
Forcing process termination may prevent forward cleanup; no claim of crash-safe cleanup.
If the app rejects modification/signing or ARM translation is incompatible, stop and
report the result. Do not bypass integrity checks or enable root.

The embedded Gadget token is not a secret from someone who can inspect that APK.
Use only a trusted isolated test emulator, never a public tunnel/forward. Never publish
private APKs, credentials or signing keys. Report includes no boot IDs, tokens or user data.

## Validation / licensing

Unit tests use synthetic APKs/ADB responses. The Frida script smoke test runs only in
an owned synthetic Python child on Linux/Windows; it is **not an Android/MuMu runtime test**.
The frozen EXE self-check opens/verifies the actual Tk window and imports pinned Frida.

Frida license: see FRIDA-COPYING.txt (wxWindows Library Licence 3.1 and referenced LGPL).
Official corresponding source/releases: https://github.com/frida/frida/releases/tag/17.24.1
and https://github.com/frida/frida-core/tree/17.24.1 . No changes to Frida binaries.
