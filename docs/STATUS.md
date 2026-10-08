# Delivery status — 8 October 2026

## Live services

- Website: https://backyard-camera.vercel.app — production, Next.js, deployed through the Vercel GitHub import.
- Source: https://github.com/spatattack/backyard-camera — public repository, as created by its owner.
- Supabase: `Backyard Camera`, project `ucibqecfqzjnvhdxiura`, Ireland (`eu-west-1`), active.
- Website configuration: project URL and publishable key in Vercel Production/Preview and local `.env.local`. No admin key.
- Device: dedicated confirmed Auth account, registered in `camera_devices`; credentials in the ignored local `device/config.json` (mode 0600).

## Verified

- Production website loads two labelled mock JPEGs, each 960×540; browser confirms both images decoded successfully.
- Date filter form navigates correctly and displays the empty-day state for 7 October.
- First live mock upload created the Storage object and matching Postgres metadata, then drained its local queue to zero.
- A previously offline capture survived a process restart and uploaded about 20 minutes later.
- Retrying an already uploaded capture verified existing bytes and metadata without overwrite or duplicate rows.
- Public object download matched the stored SHA-256.
- Supabase security advisor returned no findings after schema application.
- Nine Python queue/retry tests, eleven local Postgres grant/RLS checks, and archive date/pagination/error-state checks passed.
- Production Next.js build passed; GitHub Actions Check passed for the initial implementation and documentation revision. Latest runs: https://github.com/spatattack/backyard-camera/actions

## Remaining hardware work

Actual Pi camera capture, Wi-Fi outage recovery, systemd camera permissions, power stability and enclosure checks require access to the Raspberry Pi. Follow [HARDWARE.md](HARDWARE.md). The cloud software is ready for that bring-up.

## Operational notes

- Captures and their metadata are public by design; mock images are visibly labelled.
- Cloud retention/deletion is manual; local queue is bounded and never silently evicts pending captures.
- Default capture interval: 300 seconds. UTC archive dates. No AI ranking or daily winner yet.
- This Mac has multiple Python installations. Homebrew `/opt/homebrew/bin/python3` passed HTTPS verification; its python.org 3.11 installation has a broken certificate store. Do not disable TLS checks.
- Vercel connector project creation returned 403. Deployment succeeded using the existing signed-in dashboard after the user handled an optional account-security prompt. This does not affect Git-based deployments or the public site.
- London Drift was not modified. No admin/service-role key was acquired or exposed.

## Motion extension — 8 October 2026

- Added continuous Picamera2 preview, grayscale motion detection, ignored regions, a configurable three-frame persistence threshold, three-shot bursts, 30-second cooldown and scheduled capture fallback.
- Recorded-video replay is offline by default; explicit uploads are labelled mock.
- Existing SQLite queues gain metadata columns without deleting captures. Cloud migration adds constrained trigger/event/score fields without changing upload permissions.
- Fifteen device tests pass, including generated-video replay and legacy queue migration. Archive tests, RLS tests and the production build pass.
- Live replay smoke test uploaded one baseline plus three motion frames sharing event ID `da73f850-49b7-4fc6-8d74-aa2d320440fd`; queue drained to zero.
- Pi execution/performance remains unverified until hardware access. Person/animal recognition and daily photo selection are still not implemented.
- Latest Supabase advisor check reports an Auth configuration warning: [leaked-password protection is disabled](https://supabase.com/docs/guides/auth/password-security#password-strength-and-leaked-password-protection). No RLS finding was reported; this change did not alter Auth settings.
- Setup: [MOTION.md](MOTION.md).
