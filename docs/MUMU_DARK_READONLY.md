# Host-side known-dark-palette reader

The existing MuMu bridge remains version 1.0.0 and read-only. No new Windows bridge download is needed for these host-side changes. The MoreLogin snapshot and main branch are not changed.

## What changed

- `bubble_detector.py` infers a light or dark palette from a bounded sample of an **explicit** conversation ROI. It supports the observed neutral grey incoming / dark teal outgoing palette. Unknown palettes, clipped components, wrong-side regions and overlaps can remain unassigned. Directions and boundaries are candidates, not verified message identities.
- `chat_core.py` names the method `background_components_v2` for both memory and file paths.
- `host_dark_reader.py` is an experimental Linux/host-side Tesseract reader. It reads a saved PNG, requires an explicit ROI, and has no network, emulator controls or message sending. Example: `python host_dark_reader.py --image LOCAL.png --roi X Y WIDTH HEIGHT`.
- Install Tesseract with `rus` and `eng` in the host environment; the existing Python requirement provides Pillow. Tesseract is invoked through stdin/stdout; it does not need a temporary screenshot file.

## Important limits

The bright-text mask suppresses dim timestamp/status pixels for the observed dark palette, but **can also omit grey or coloured message text and corrupt emoji**. It is not a complete transcript. Low-confidence tokens are preserved and flagged, not silently deleted. A white message body containing a time-like string is not removed just because it looks like a timestamp.

The conversation ROI in the first real-device acceptance check was selected manually from the observed screen. General automatic exclusion of profile cards, keyboard and headers is **not** implemented. Do not blindly reuse the same ROI after scrolling, rotating or changing resolution/screens.

A manual visual comparison on the first authorized 900x1600 screen found two visible bubbles. The old detector found zero; the updated detector found two in the explicit conversation ROI. Incoming text was read correctly in that sample. A coloured emoji in the outgoing text was misread as a low-confidence Latin character and remained flagged. This is one real screen, not proof of accuracy across conversations.

No personal screenshot, message content, name, avatar or actual OCR result is included in the committed fixtures. New regressions are synthetic only: known dark palette, scale/colour variation, blank screens, white text false positives, wrong-side components, clipped bubbles, one-pixel gaps, explicit ROI exclusion, OCR token preservation and engine errors.

Host tests: 84 passed. Conversation identity, message freshness, full history, duplicate suppression and sending are **not implemented/verified**. Do not use these candidates as an automatic-send trigger.
