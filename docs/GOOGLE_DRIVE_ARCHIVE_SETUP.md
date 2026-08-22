# Temporary Google Drive archive — ₹0 setup

Infinity Research AI does **not** wait for TeraBox approval. Google Drive can be used as the temporary bulk/archive provider while the research engine stays provider-neutral.

## Safety rules

- Keep `ZERO_COST_ONLY=true`.
- Do not put Google OAuth tokens, client secrets or rclone config in GitHub or the Android APK.
- Do not enable paid Google Cloud billing for this project just to increase Drive/API quota.
- If Drive quota/storage/API access is exhausted, archive upload fails and the local file is retained/retried. The app must not switch to paid storage automatically.
- A local file may be deleted only after the cloud copy is independently verified by the archive manifest.

## One-time laptop setup

1. Install the open-source `rclone` CLI from its official project.
2. Create a Google Drive OAuth client for your own project/account when possible rather than relying on a shared public client ID.
3. Run `rclone config` on the laptop and create a Google Drive remote, for example `infinitydrive`.
4. Complete the browser OAuth login for the Google account whose Drive storage should be used.
5. Keep rclone's config file private. It contains OAuth material and must never be committed.
6. Test the remote locally with a harmless listing before enabling the backend provider.

## Backend `.env`

```env
CLOUD_ARCHIVE_PROVIDER=google-drive-rclone
GOOGLE_DRIVE_RCLONE_REMOTE=infinitydrive
GOOGLE_DRIVE_ARCHIVE_ROOT=InfinityResearchAI
RCLONE_EXE=rclone
RCLONE_TIMEOUT_SECONDS=1800
```

If `rclone.exe` is not on PATH, set `RCLONE_EXE` to its local executable path in your private `.env` only.

## What the backend does

The adapter uses an exact-file `rclone copyto` operation and then reads remote metadata. `ArchiveCoordinator` independently verifies remote size and SHA-256 when the provider exposes that hash. If the hash is unavailable, size is still required to match; the local copy remains until the archive manifest says `verified`.

Failed upload or verification is written to the durable archive retry queue with bounded exponential backoff. Retry operations never auto-delete the local copy.

## Storage layout

- GitHub: source code, tests, docs and version history.
- `D:\InfinityResearchAI`: bounded active working/runtime files.
- Google Drive `InfinityResearchAI/...`: temporary large archive.
- TeraBox: optional future migration target only if official API access and zero-cost terms are confirmed.

## Future TeraBox migration

Cloud paths and provider details stay outside the research engine. When an official TeraBox adapter is available, Drive files can be copied/verified into TeraBox while preserving archive metadata. The core research pipeline should not require a rewrite.
