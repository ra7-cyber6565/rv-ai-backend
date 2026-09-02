# Temporary Google Drive archive — ₹0 setup

Infinity Research AI does **not** wait for TeraBox approval. Google Drive can be used as the temporary bulk/archive provider while the research engine stays provider-neutral.

## Safety rules

- Keep `ZERO_COST_ONLY=true`.
- Do not put Google OAuth tokens, client secrets, rclone config, crypt password or crypt salt in GitHub or the Android APK.
- Do not enable paid Google Cloud billing for this project just to increase Drive/API quota.
- If Drive quota/storage/API access is exhausted, archive upload fails and the local file is retained/retried. The app must not switch to paid storage automatically.
- A local file may be deleted only after the cloud copy is independently verified by the archive manifest.
- If encrypted archive mode is required, the backend fails closed unless the selected rclone remote is locally verified as backend type `crypt`.

## One-time laptop setup

1. Install the open-source `rclone` CLI from its official project.
2. Create a Google Drive OAuth client for your own project/account when possible rather than relying on a shared public client ID.
3. Run `rclone config` on the laptop and create a Google Drive remote, for example `infinitydrive`.
4. Complete the browser OAuth login for the Google account whose Drive storage should be used.
5. Keep rclone's config file private. It contains OAuth material and must never be committed.
6. Test the remote locally with a harmless listing before enabling the backend provider.

## Recommended optional encryption: rclone crypt

For archive-at-rest encryption, use rclone's mature `crypt` backend instead of application-written crypto. Infinity Research AI does not receive, generate or store the crypt password/salt.

1. Run interactive `rclone config` again.
2. Create another remote, for example `infinitycrypt`, with backend type **crypt**.
3. Point that crypt remote at a folder on the already-authenticated Drive remote, for example `infinitydrive:InfinityResearchAIEncrypted`.
4. Let rclone generate/use strong crypt credentials interactively. Do **not** paste them into `.env`, source code, GitHub issues or shell-history commands.
5. Verify locally with `rclone listremotes --long`. The selected archive remote must appear with type `crypt` before enabling fail-closed encryption mode.
6. Keep an independent recovery copy of the crypt password/salt or the private rclone configuration in a secure offline location. Losing the crypt credentials can make the archive permanently unreadable. Do not keep the only recovery copy inside the same encrypted Drive archive.

The underlying Google Drive remote then sees encrypted file contents and, depending on the crypt configuration, encrypted file/directory names. The backend still operates on the logical decrypted path through rclone.

## Backend `.env`

Plain Drive archive:

```env
CLOUD_ARCHIVE_PROVIDER=google-drive-rclone
GOOGLE_DRIVE_RCLONE_REMOTE=infinitydrive
GOOGLE_DRIVE_ARCHIVE_ROOT=InfinityResearchAI
GOOGLE_DRIVE_ARCHIVE_REQUIRE_CRYPT=false
RCLONE_EXE=rclone
RCLONE_TIMEOUT_SECONDS=1800
```

Encrypted archive (recommended when cloud copies may contain private research data):

```env
CLOUD_ARCHIVE_PROVIDER=google-drive-rclone
GOOGLE_DRIVE_RCLONE_REMOTE=infinitycrypt
GOOGLE_DRIVE_ARCHIVE_ROOT=InfinityResearchAI
GOOGLE_DRIVE_ARCHIVE_REQUIRE_CRYPT=true
RCLONE_EXE=rclone
RCLONE_TIMEOUT_SECONDS=1800
```

When `GOOGLE_DRIVE_ARCHIVE_REQUIRE_CRYPT=true`, startup/provider construction refuses to archive unless `rclone listremotes --long` identifies the configured remote as type `crypt`. A normal Drive remote, missing rclone, unreadable config or unverifiable type is treated as **not ready**; local files remain retained.

If `rclone.exe` is not on PATH, set `RCLONE_EXE` to its local executable path in your private `.env` only.

## What the backend does

The adapter uses an exact-file `rclone copyto` operation and then reads remote metadata. `ArchiveCoordinator` independently verifies remote size and SHA-256 when the provider exposes that hash. If the hash is unavailable, size is still required to match; the local copy remains until the archive manifest says `verified`.

If the selected remote is a verified rclone crypt remote, encryption/decryption happens inside rclone before/after the underlying Drive backend. The Infinity Research AI code does not implement cryptography itself and never calls `rclone config show`, so OAuth/crypt secret material is not pulled into API status output.

Failed upload or verification is written to the durable archive retry queue with bounded exponential backoff. Retry operations never auto-delete the local copy.

## Recovery drill before trusting cleanup

Before allowing cloud-verified cleanup to matter for important data, do one harmless recovery test:

1. Archive a small non-sensitive test file through the configured crypt remote.
2. From a separate temporary folder, use the same private rclone configuration to copy the logical file back through `infinitycrypt:`.
3. Compare the restored file with the original locally.
4. Only after successful recovery should the encrypted remote be treated as a dependable archive destination.

This drill does not change the backend's deletion rule: local deletion still requires the archive manifest's verified state.

## Storage layout

- GitHub: source code, tests, docs and version history.
- `D:\InfinityResearchAI`: bounded active working/runtime files.
- Google Drive: temporary large archive, preferably ciphertext through `infinitycrypt`.
- TeraBox: optional future migration target only if official API access and zero-cost terms are confirmed.

## Future TeraBox migration

Cloud paths and provider details stay outside the research engine. When an official TeraBox adapter is available, Drive files can be copied/verified into TeraBox while preserving archive metadata. The core research pipeline should not require a rewrite.