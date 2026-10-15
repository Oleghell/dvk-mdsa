# MuMu draft-only bridge 1.1.0

Opt-in replacement for the read-only bridge. Old read-only files and MoreLogin snapshot remain unchanged. This version adds ONE permitted mutation: put exactly `Как настроение?)` into the unique EMPTY DrugVokrug edit field. There is no send, click, Enter, IME action or arbitrary shell tool. It does not overwrite an existing draft. One instrumentation attempt per process session, including uncertain/refused results; no blind retries.

## Запуск Windows

1. Остановите старый мост. Распакуйте весь новый архив в отдельную папку.
2. Откройте MuMu и нужный чат ДругВокруг. Оставьте поле сообщения пустым.
3. Запустите `MuMu-draft-only.exe`, выберите ADB, нажмите «Разрешить подключение» и подтвердите новый режим.
4. Будет установлен тестовый APK `com.dvk.drafthelper` с названием «DVK draft-only helper». Он не запрашивает разрешения, не имеет сети, служб, автозапуска, клавиатуры или действий отправки. Используется стандартная Android instrumentation и ACTION_SET_TEXT; существующие accessibility-службы не выключаются.
5. Адрес и новый ключ используйте для нового MCP-подключения. Ключ — только в защищённое поле Bearer/Header, не в чат. Держите окно открытым. «Остановить» отзывает новые запросы, но не отменяет уже начатую запись.
6. При ошибке/неопределённом результате проверьте экран. Автоматического повтора или очистки поля нет. Удалить помощник можно вручную в настройках приложений MuMu. Мост не удаляет приложения.

## Guards and limits

The agent first reads the exact visible accessibility header labels with the read-only context tool (no full-history dump), then a fresh screenshot. This supports header text that combines display name and age without guessing its spacing. The draft tool requires that screenshot's SHA256 and the exact visible header name. Before mutation the bridge checks the screenshot has not changed. Android then checks the foreground package, visible header name, unique enabled non-password editable field and that the field is empty. It re-resolves the active tree immediately before ACTION_SET_TEXT and verifies text readback afterward. No focus/click/key actions are used.

These checks are best-effort, not atomic and **not a unique recipient/account identity**. Same display names can collide. Do not switch chat during the operation. Apps can implement unexpected behavior; test fixtures cannot prove third-party app internals. Only a fresh real-device screenshot and field readback confirm the actual draft. The program does not implement any send action, but cannot make promises about undocumented target-app behavior.

Cloudflare remains a third-party intermediary for screen data; temporary Quick Tunnel URLs and keys change on restart. Every MCP request requires the per-session bearer key. ADB stays bound to the existing loopback transport; the program does not expose ADB publicly. The helper APK is hash-checked against the shipped manifest before installation; keep package files together. No screenshots, names, tokens or chat text are saved by the bridge. Clipboard history may retain copied keys.

Android CI uses an invented offline fixture in a disposable emulator, NOT the real application or account. The fixture APK is never included in the user package. Tests check exact Cyrillic, unchanged send count, existing-draft preservation, wrong name and wrong app refusal. Python tests cover authentication, screenshot changes, single attempt, command allowlist and APK integrity. Actual MuMu behavior is a separate acceptance check.

Official Android APIs: https://developer.android.com/reference/android/view/accessibility/AccessibilityNodeInfo#ACTION_SET_TEXT
https://developer.android.com/reference/android/app/UiAutomation#FLAG_DONT_SUPPRESS_ACCESSIBILITY_SERVICES
