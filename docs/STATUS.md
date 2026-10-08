# Delivery status — 8 October 2026

## Created and verified

- Source: https://github.com/spatattack/backyard-camera (the repository was created **public** by its owner).
- Supabase: `Backyard Camera`, project `ucibqecfqzjnvhdxiura`, Ireland (`eu-west-1`), active.
- One additive migration applied; `camera_devices`, `captures`, public JPEG bucket, constrained device insert policies.
- Supabase security advisor: no findings.
- Public metadata endpoint returned HTTP 200 (empty archive before first upload).
- Nine Python queue/retry tests passed.
- Eleven local PostgreSQL privilege/RLS checks passed using PGlite auth/storage fixtures.
- Archive validation, UTC day filtering, pagination and failure-state tests passed.
- Production Next.js build passed.
- GitHub Actions Check passed: https://github.com/spatattack/backyard-camera/actions/runs/37802993215
- Actual Mac mock JPEG capture persisted in SQLite and was readable after reopening the queue.
- Website browser check: archive UI rendered with its explicit setup state.

## Pending verification

- Device Auth account/password configuration and first live mock upload.
- Vercel Git import/deploy. Connector creation returned 403 for this account; dashboard access works, but its optional 2FA prompt requires the user to handle it after automatic approval review blocked dismissal.
- Actual Pi camera capture, Wi-Fi recovery, systemd permissions, power and enclosure checks require hardware access.

No admin/service-role key was obtained or placed on the Pi/site. `device/config.json` and `.env.local` are local ignored files. London Drift was not changed. No AI ranking or automatic cloud deletion was added.
