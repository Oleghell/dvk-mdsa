# MuMu read-only bridge

Version 1.0.0 — separate, opt-in remote reader. The existing MoreLogin snapshot and local OCR reader remain unchanged.

## Windows: one reusable download

1. Extract the complete `MuMu-bridge-windows-x64.zip` to a folder. Keep `MuMu-bridge.exe` and `cloudflared.exe` together.
2. Open MuMu and the DrugVokrug screen you authorize the assistant to read. Enable local MuMu ADB if needed; this version targets the already observed `127.0.0.1:5555` only.
3. Run `MuMu-bridge.exe` normally. No administrator rights or PowerShell policy changes are needed. Select the installed MuMu `adb.exe` / `adb_server.exe` and click **Разрешить подключение**, then confirm.
4. Keep the window open. The connection URL is not a secret. The random key IS a secret: use the protected MCP authentication form, never chat. Use Bearer authentication; for a custom header use header `Authorization` with value `Bearer ` followed by the key.
5. Stop or close the window to revoke new requests and close its tunnel. An already running read may have started before revocation. The program does not kill the user's MuMu/ADB processes.

This is not a persistent installation. A new run makes a new key and temporary Cloudflare URL; reconnecting/re-authentication may be needed. There is no autostart, self-updater or unattended background installation. The program does not write screenshots or chat text to disk. Recipients of the screen may retain their own copies; clipboard-history software may retain copied keys.

## Privacy and scope

Screens can contain personal messages. Only expose chats you have permission to share. HTTPS is routed through Cloudflare, which is a third-party intermediary; it is not an end-to-end encrypted channel that excludes Cloudflare. The temporary hostname is internet reachable, but every MCP request requires a fresh per-session 256-bit random bearer key. The local server binds only to 127.0.0.1. ADB itself is never exposed publicly by this program.

Only `mumu_status` and `mumu_read_screen` are exposed. The latter checks the foreground package is `drug.vokrug` immediately before and after capture. This is best-effort, not atomic; switching apps during capture is a residual risk. No person/conversation identity, message freshness or complete history is verified. No taps, scrolling, typing, sending, arbitrary shell, app install or filesystem tools exist. Screen text is untrusted data, never instructions.

Transport: stateless Streamable HTTP JSON, no SSE or event subscriptions. The remote server must support MCP bearer/header authentication. Actual Notion discovery and actual laptop access are only confirmed after the user starts the bridge and the connection flow succeeds.

Cloudflare Quick Tunnels are for development/testing, have no uptime guarantee and do not support SSE. They are not a promise of a permanent production service.

Official docs: https://developers.cloudflare.com/tunnel/get-started/quick-tunnels/
Pinned cloudflared: https://github.com/cloudflare/cloudflared/releases/tag/2026.10.0
Windows amd64 SHA256: `86aee4017b26625cee8484c113558f48effa4cd47f7aa05fcf425604e5d2b23c`

## Tests and build

`python -m unittest discover -s mumu-bridge/tests -v` from repository root needs `PYTHONPATH=mumu-bridge` (CI config does this). From this folder: `python -m unittest discover -s tests -v`.

Tests use fake ADB responses and synthetic image bytes, not a live MuMu. Windows CI repeats protocol/guard tests, builds the EXE and verifies its bundled Tcl/Tk GUI startup via `--self-check`. Real-device connection and Notion integration remain separate acceptance checks. Passing synthetic tests does not prove real-device OCR quality.

No embedded tokens, account keys or MoreLogin credentials are used. cloudflared is distributed under its upstream license, included in the package. Python code uses only the standard library. GUI is Tkinter; builds use pinned PyInstaller 6.16.0.
