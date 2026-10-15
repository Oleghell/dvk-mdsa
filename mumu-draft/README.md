# MuMu draft-only bridge 1.1.1 — visual header verification

This version fixes the actual application's inaccessible header: it does not rely on accessibility name text. Instead, the agent must visually review a fresh screen and provide its full PNG SHA256 plus its header RGB SHA256. The host rechecks the complete screenshot. Android independently captures the display and compares the fixed header band immediately before ACTION_SET_TEXT and during readback.

## Запуск

1. Остановите старый мост. Распакуйте весь архив в новую папку.
2. Запустите `MuMu-draft-only.exe`, выберите прежний ADB и подтвердите новый режим.
3. Установится отдельный тестовый помощник `com.dvk.drafthelper.visual` («DVK visual draft helper»). Старый `com.dvk.drafthelper` не изменяется и не удаляется; его можно вручную удалить в настройках MuMu. У обоих нет служб/автозапуска.
4. Держите нужный чат и пустое поле открытыми, не переключайте экран во время операции. Новый адрес и ключ нужно подключить заново. Ключ — только в защищённое поле авторизации, не в чат.

## Exact scope and limitations

- Only the observed **900×1600 portrait layout** is supported. Header band is x=0,y=48,width=900,height=176, covering the observed name/avatar/status area but excluding the phone clock. Other layouts fail closed.
- Comparison is exact SHA256 of row-major RGB bytes, not OCR or a claim of a unique account ID. Animated avatar/status changes or rendering differences can safely block the draft.
- The intended chat must first be confirmed visually on the fresh screenshot by the agent/user. A reference image of the wrong chat would still be the wrong reference; the hash is not independent semantic identity verification.
- Foreground package must remain `drug.vokrug`; there must be exactly one enabled visible editable non-password field and it must be empty. Existing draft is never cleared or replaced.
- One attempt to set exactly `Как настроение?)` per bridge process; unknown/refused instrumentation results are not blindly retried.
- Only ACTION_SET_TEXT is used. No click, Enter, editor action, arbitrary text, arbitrary shell or send command exists. Afterward, the text and header image are rechecked. Checks are best-effort, not atomic; do not interact during the operation.
- APK has no requested permissions, network, services or boot receiver. Android instrumentation is run only on demand through the user's authorized local ADB. Existing accessibility services are not disabled.
- Screens pass through Cloudflare with per-session bearer authentication. ADB is not exposed publicly. Closing/revoking blocks new calls but cannot undo an already started field change. No screenshots, names, tokens or chat text are written by the bridge.

## Regression checks

Python tests cover two independent hashes, clock exclusion vs header changes, wrong dimensions, authentication, fixed phrase, command allowlist and one attempt. Android CI renders an invented fixture whose name is deliberately inaccessible, then checks that ADB PNG and UiAutomation RGB header hashes agree. It checks exact Cyrillic with send count zero, existing-draft preservation, stale/wrong header and wrong foreground-app refusal. Fixture APK and signing keystore are never included in the user package. Actual MuMu operation still requires a separate real-device acceptance check.
