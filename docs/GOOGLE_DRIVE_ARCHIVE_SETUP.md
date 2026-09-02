# Temporary Google Drive archive — ₹0 setup

Infinity Research AI does **not** wait for TeraBox approval. Google Drive can be used as the temporary bulk/archive provider while the research engine stays provider-neutral.

## Safety rules

- Keep `ZERO_COST_ONLY=true`.
- Do not put Google OAuth tokens, client secrets, rclone config, crypt password or crypt salt in GitHub or the Android APK.
- Do not enable paid Google Cloud billing for this project just to increase Drive/API quota.
- If Drive quota/storage/API access is exhausted, archive upload fails and the local file is retained/retried. The app must not switch to paid storage automatically.
- A local file may be deleted only after the exact cloud copy has a matching SHA-256 proof in the archive manifest. Matching size alone is **not** enough for destructive cleanup.
- Once Google Drive archiving is enabled, encrypted rclone `crypt` is the **fail-closed default**. A plain Drive remote works only if the operator deliberately sets `GOOGLE_DRIVE_ARCHIVE_REQUIRE_CRYPT=false`.

## One-time laptop setup

1. Install the open-source `rclone` CLI from its official project.
2. Create a Google Drive OAuth client for your own project/account when possible rather than relying on a shared public client ID.
3. Run `rclone config` on the laptop and create a Google Drive remote, for example `infinitydrive`.
4. Complete the browser OAuth login for the Google account whose Drive storage should be used.
5. Keep rclone's config file private. It contains OAuth material and must never be committed.
6. Test the remote locally with a harmless listing before enabling the backend provider.

## Secure default: rclone crypt

For archive-at-rest encryption, use rclone's mature `crypt` backend instead of application-written crypto. Infinity Research AI does not receive, generate or store the crypt password/salt.

1. Run interactive `rclone config` again.
2. Create another remote, for example `infinitycrypt`, with backend type **crypt**.
3. Point that crypt remote at a folder on the already-authenticated Drive remote, for example `infinitydrive:InfinityResearchAIEncrypted`.
4. Let rclone generate/use strong crypt credentials interactively. Do **not** paste them into `.env`, source code, GitHub issues or shell-history commands.
5. Verify locally with `rclone listremotes --long`. The selected archive remote must appear with type `crypt` before enabling Drive archive with the default security policy.
6. Keep an independent recovery copy of the crypt password/salt or the private rclone configuration in a secure offline location. Losing the crypt credentials can make the archive permanently unreadable. Do not keep the only recovery copy inside the same encrypted Drive archive.

The underlying Google Drive remote then sees encrypted file contents and, depending on the crypt configuration, encrypted file/directory names. The backend still operates on the logical decrypted path through rclone.

## Backend `.env`

Encrypted archive — recommended/default security posture:

```env
CLOUD_ARCHIVE_PROVIDER=google-drive-rclone
GOOGLE_DRIVE_RCLONE_REMOTE=infinitycrypt
GOOGLE_DRIVE_ARCHIVE_ROOT=InfinityResearchAI
GOOGLE_DRIVE_ARCHIVE_REQUIRE_CRYPT=true
RCLONE_EXE=rclone
RCLONE_TIMEOUT_SECONDS=1800
```

Plain Drive archive — explicit operator opt-out from at-rest crypt protection:

```env
CLOUD_ARCHIVE_PROVIDER=google-drive-rclone
GOOGLE_DRIVE_RCLONE_REMOTE=infinitydrive
GOOGLE_DRIVE_ARCHIVE_ROOT=InfinityResearchAI
GOOGLE_DRIVE_ARCHIVE_REQUIRE_CRYPT=false
RCLONE_EXE=rclone
RCLONE_TIMEOUT_SECONDS=1800
```

If the flag is absent, the code behaves as though `GOOGLE_DRIVE_ARCHIVE_REQUIRE_CRYPT=true`. Startup/provider construction refuses to archive unless `rclone listremotes --long` identifies the configured remote as type `crypt`. A normal Drive remote, missing rclone, unreadable config or unverifiable type is treated as **not ready**; local files remain retained. This archive failure does not make completed research fail.

If `rclone.exe` is not on PATH, set `RCLONE_EXE` to its local executable path in your private `.env` only.

## What the backend does

The adapter first uploads one exact logical file with `rclone copyto`, then reads remote metadata with `rclone lsjson --stat --files-only --hash`.

For destructive-retention safety the backend requires a matching **SHA-256**, not just the same byte count:

- if the selected backend exposes a valid native SHA-256, that hash is compared with the local file;
- if native SHA-256 is unavailable, the adapter runs `rclone hashsum SHA256 <logical-remote-file> --download`, which reads the remote object back through rclone and hashes the logical bytes locally;
- with a `crypt` remote, that read goes back through the crypt layer, so the checksum is over the decrypted logical file rather than the ciphertext object stored by Drive;
- if the download/hash step times out, is quota-limited, produces no valid SHA-256, or otherwise fails, verification fails closed and the local copy is retained/retried.

This stronger verification can use extra Drive bandwidth/time because a provider without native SHA-256 may need one complete read-back after upload. That cost is intentional: the app prefers retaining a local duplicate over deleting the only known-good copy on the strength of file size alone.

The archive manifest records verification strength separately. `verified=true` can describe an observed matching remote object, but **local cleanup additionally requires `checksum_verified=true` / `verification_method=size+sha256`**. Old manifest rows that predate this proof are treated as checksum-unverified until revalidated.

The final verification check, local removal and manifest deletion mark are serialized against concurrent re-upload attempts. This closes the verification-to-delete race where a cloud object could otherwise start being replaced after a successful check but just before the local copy was deleted.

If the selected remote is a verified rclone crypt remote, encryption/decryption happens inside rclone before/after the underlying Drive backend. The Infinity Research AI code does not implement cryptography itself and never calls `rclone config show`, so OAuth/crypt secret material is not pulled into API status output.

Failed upload or verification is written to the durable archive retry queue with bounded exponential backoff. Retry operations never auto-delete the local copy.

## Recovery drill before trusting cleanup

Before allowing cloud-verified cleanup to matter for important data, do one harmless recovery test:

1. Archive a small non-sensitive test file through the configured crypt remote.
2. Confirm the backend archive record reached checksum-verified state.
3. From a separate temporary folder, use the same private rclone configuration to copy the logical file back through `infinitycrypt:`.
4. Compare the restored file with the original locally.
5. Only after successful recovery should the encrypted remote be treated as a dependable archive destination.

This drill does not weaken the backend's deletion rule: local deletion still requires the exact archive record to be cloud-verified **and** SHA-256 verified.

## Storage layout

- GitHub: source code, tests, docs and version history.
- `D:\InfinityResearchAI`: bounded active working/runtime files.
- Google Drive: temporary large archive, ciphertext through `infinitycrypt` by default.
- TeraBox: optional future migration target only if official API access and zero-cost terms are confirmed.

## Future TeraBox migration

Cloud paths and provider details stay outside the research engine. When an official TeraBox adapter is available, Drive files can be copied/verified into TeraBox while preserving archive metadata. Any future provider must meet the same deletion boundary: exact destination + matching content checksum before local cleanup. The core research pipeline should not require a rewrite.