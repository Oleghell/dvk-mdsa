# Pinned helper runtime v1.3.2

`helper-v132.apk.base64` is the already tested helper from the user-supplied
`MuMu-navigation-update-v1.3.2.zip`, not a signing key or a newly built APK.
SHA256: `700d240c6adbf08066f5de2314d447381b4303d6c76aef5bc0a06d722a2c8cd1`.
The archive manifest declared the same checksum; that check establishes byte
identity, not independent provenance or authorship certification.

The helper instruments its own `com.dvk.navigation.v132` package, not the fixture
package. Its signing key need not match the synthetic fixture's ephemeral key.
`build.sh` still compiles the native source; packaging verifies its DEX equals
the pinned release DEX, source and manifest SHA256 values are pinned too (LF/CRLF is normalized; code changes are not).
The exact packaged APK is installed and exercised by Android CI before upload.
Any mismatch blocks the build; changing native code requires a deliberate
new helper release and migration plan. Do not replace constants to skip review.

This prevents repeated signer changes in bridge-only updates. An installation
from the per-run-signed v1.4.0/v1.4.1 jobs still needs one explicitly approved
local migration. No signing private key is stored, exported or requested.
