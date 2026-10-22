# Fixed cached-model route evidence

Source: user-provided messages-navigation-definitions.json (metadata catalog;
no message bodies). The full private report is not committed.

- DV.Messages.dll / DV.Messages / ChatsViewController.m_MessagesManager.
- DV.Messages / MessagesManager.get_Chats -> DV.CMs.ChatsCM.
- MessagesManager.get_MessagesRouter -> DV.Routers.Messages.MessagesRouter.
- MessagesRouter.ShowChat(Chat, EventSourcesContext, OpenChatMethod) -> Void.
- Both context and method types are in DV.dll, empty namespace.
- Chat/account/peer and last-message scalar getters reuse the verified browser.

The 1.2.7 catalog omitted nested enum owners and its synthetic fixture wrongly
exposed the route enums as top-level classes. This caused a real model-route stop.
The user-supplied pinned APK definitions now confirm both nested enums belong to
DV.Analytics.Stat. 1.2.8 resolves their classes from ShowChat parameters and checks
exact declaring owner, image, names, Int32 base and immutable named enum fields.
MESSAGES / LIST_ITEM_CLICK are read through field_static_get_value, never default0.
See DIALOG-ROUTE-APK-EVIDENCE.json for definition identities and APK SHA-256.
The model field/collection contracts and all pre/post-open checks remain strict.
The updated native fixture rejects top-level lookups and tests wrong enum owners,
missing/nonliteral fields and wrong base/type before any route action.
This is APK-definition and fixture verified; real-device behavior is not confirmed.

Reads execute on the verified main-thread callback, objects use balanced GC
handles/scopes, collection and selection are rechecked before invoking ShowChat.
Only a last-message header identity error can be a local skip; base model errors,
managed exceptions, changed collection or post-open identity remain fatal.
No list load, refresh, server paging, text getter, native offset, swipe or tap.
Transport slices contain <=64 cached models; each scan tick reads <=2 models.
