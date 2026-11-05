# SPEC — App signing runbook (rotated out of `App/AGENTS.md` §10)

> Rotated 2026-11-05 by the crown docs pass, **verbatim** — nothing deleted, only moved, so that
> `App/AGENTS.md` (auto-loaded into every App agent) fits the byte ceiling enforced by
> `Fast_Fetch/test_docs_invariants.py` `ByteBudgetTests`. The law still lives in the auto-loaded
> file; this is the reference prose and the retired failure history.
>
> **Status correction (measured 2026-11-05, unauthenticated public GitHub API):** release `v1.0.4`
> is published with assets `radd-stream-1.0.4.apk`, `radd-stream-1.0.4.aab`,
> `radd-stream-1.0.4-SHA256SUMS.txt`, and tags `v1.0.0`–`v1.0.4` exist. The malformed-secret
> diagnosis below is the state **before** `b99814e` and is kept for the audit trail only.

---

## 10. Signing Configuration

This section previously printed a sample that `app/build.gradle.kts` does not contain —
`android.util.Base64.decode(...)` is an **Android runtime API and is not on the Gradle script's
classpath**, so the block as written could never have configured a build. What the file actually
runs (`App/app/build.gradle.kts:110-126`, verified at `a51c0c4`):

```kotlin
signingConfigs {
    create("release") {
        val keystoreBase64 = System.getenv("KEYSTORE_BASE64") ?: ""
        val storePassword  = System.getenv("KEY_STORE_PASSWORD") ?: ""
        val keyAlias       = System.getenv("KEY_ALIAS") ?: ""
        val keyPassword    = System.getenv("KEY_PASSWORD") ?: ""

        if (keystoreBase64.isNotEmpty() && storePassword.isNotEmpty()) {
            val keystoreFile = File(layout.buildDirectory.asFile.get(), "radd-release.jks")
            keystoreFile.parentFile?.mkdirs()
            keystoreFile.writeBytes(Base64.getDecoder().decode(keystoreBase64))  // java.util, imported at :3
            storeFile = keystoreFile
            this.storePassword = storePassword
            this.keyAlias = keyAlias
            this.keyPassword = keyPassword
        }
    }
}
```

Two consequences an App agent needs before spending a release run:

- The config is applied **only when both** `KEYSTORE_BASE64` and `KEY_STORE_PASSWORD` are non-empty,
  and the keystore is written under `app/build/` (never to the source tree, never committed).
- `Base64.getDecoder()` is the strict **basic** codec: no line breaks accepted, and a value whose
  length is not a whole base64 quantum throws. Measured on the release run log:
  `java.lang.IllegalArgumentException: Last unit does not have enough valid bits` at
  `build.gradle.kts:120`, `BUILD FAILED in 4s` — it dies during **configuration**, before any Kotlin
  compiles, so no compile error or lint error is ever reached. That exception is the *stored secret*
  being malformed, not this code being wrong: the keystore on the VM re-encodes cleanly
  (`/home/ubuntu/raddstream-release.jks`, 2,752 bytes → 3,672 base64 chars ending `==`, strict
  round-trip OK). **Fix it by re-entering the secret (`base64 -w 0` of that file), not by editing
  this block** — switching to `getMimeDecoder()` would silently accept a truncated keystore instead
  of refusing it.

**One-time keystore generation** (run in GitHub Codespaces terminal — no local install needed):
```bash
# Open Codespaces on the repo, open terminal, run:
keytool -genkey -v \
  -keystore radd-release-key.jks \
  -keyalg RSA -keysize 2048 \
  -validity 10000 \
  -alias radd-key \
  -dname "CN=RADD Stream, O=RADD, C=US"

# Encode for GitHub Secret:
base64 -w 0 radd-release-key.jks

# Add to GitHub: Settings → Secrets → Actions:
#   KEYSTORE_BASE64 = (paste output above)
#   KEY_STORE_PASSWORD = (the password you chose)
#   KEY_ALIAS = raddstream
#   KEY_PASSWORD = (the key password you chose)
```

> **Status (Measured 2026-10-30):** All 4 release signing secrets are active in GitHub Actions Secrets. The release keystore is backed up on Oracle VM at `/home/ubuntu/raddstream-release.jks`. Tagging `v*.*.*` automatically triggers `.github/workflows/release.yml` which builds, signs, verifies, and publishes release APKs + AABs to GitHub Releases.

---
