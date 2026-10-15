# Read-only host chat observer

`host_chat_observer.py` adds persistent baselines and conservative visible-content deduplication to the experimental dark-screen reader. It is host-side only: the Windows MuMu read-only bridge does not need an update.

## Usage

```
python host_chat_observer.py --image LOCAL.png --roi X Y W H --header-roi X Y W H --avatar-roi X Y W H --state PRIVATE.sqlite3
```

All regions are explicitly selected for a known layout. The name/header crop must contain legible bright name text, not the clock, online status or buttons. The avatar crop should contain the stable header avatar only. The conversation ROI must exclude profile card, input field and keyboard. The program is not a general screen-layout parser and does not operate unattended.

## State and behavior

- A visual context key hashes the explicit layout, name/header pixels, avatar pixels and resolution. The OCR name is a **label candidate**, not a unique or verified account identifier.
- First observation of a context establishes a baseline and creates **no reply trigger**.
- A repeated conversation-region image is ignored even when the device clock changes outside it.
- If the visible region changes, incoming content signatures already seen in this context are suppressed. Changed unseen incoming text is returned **for human review only**, not labelled a verified new message. Scrolled-in old text may be unseen to the observer; two genuine identical messages may be suppressed.
- Low-confidence incoming OCR or unreadable name blocks observation. Low-confidence outgoing emoji is not treated as an incoming message.
- Changing visual context/layout establishes another baseline. An animated or changed avatar/name style may unnecessarily reset the baseline. Different people with identical name/avatar can collide; identity is never asserted.
- SQLite stores hashes only, not names, message text, avatars or screenshots. Hashes are not a promise of anonymization. Keep the local state file private and out of GitHub.
- Transactions serialize concurrent state updates. State is bounded at 100 visual contexts / 1000 content signatures per context. Reaching the limit blocks further observations; old signatures are not silently evicted and re-triggered.

No text generator, draft queue, scheduler, background polling, input control or sending is implemented in this module. Drafting and reviewing remain explicit agent/user actions. All results set `identity_verified=false`, `freshness_verified=false`, `automatic_reply_enabled=false`, `messages_sent=0`.

## Acceptance checks

99 Python unit tests passed on the Linux host. New tests cover baselines, unchanged images, repeated text, context switching/return, uncertain OCR, persistence, capacity limits and absence of plaintext message content in SQLite.

On two authorized real MuMu snapshots with the same visible conversation and different phone clock values: first result `baseline_only`, second `unchanged_visible_region`, zero review candidates, zero messages sent. This checks one real layout only; it does not verify a person's account identity or actual new-message detection. Personal screenshots, OCR output and state database are not committed to the repository.
