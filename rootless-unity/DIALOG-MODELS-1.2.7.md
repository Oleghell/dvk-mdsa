# Fixed cached-model route evidence

Source: user-provided messages-navigation-definitions.json (metadata catalog;
no message bodies). The full private report is not committed.

- DV.Messages.dll / DV.Messages / ChatsViewController.m_MessagesManager.
- DV.Messages / MessagesManager.get_Chats -> DV.CMs.ChatsCM.
- MessagesManager.get_MessagesRouter -> DV.Routers.Messages.MessagesRouter.
- MessagesRouter.ShowChat(Chat, EventSourcesContext, OpenChatMethod) -> Void.
- Both context and method types are in DV.dll, empty namespace.
- Chat/account/peer and last-message scalar getters reuse the verified browser.

The catalog truncates inherited generic collection and context definitions.
At runtime the exact manager field owner/nonstatic class type is verified,
then inherited Count/Item(Int32) signatures returning Chat. Context must be a
bounded value type (default zero, 1..256 bytes), method an Int32 enum (default0).
No reference context constructor or unknown enum value is fabricated. Unsupported
ABI stops before action. This is fixture-tested, not live-device confirmed.

Reads execute on the verified main-thread callback, objects use balanced GC
handles/scopes, collection and selection are rechecked before invoking ShowChat.
Only a last-message header identity error can be a local skip; base model errors,
managed exceptions, changed collection or post-open identity remain fatal.
No list load, refresh, server paging, text getter, native offset, swipe or tap.
Transport slices contain <=64 cached models; each scan tick reads <=2 models.
