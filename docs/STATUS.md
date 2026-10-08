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

- Device Auth account configured and registered; first live mock JPEG uploaded, metadata inserted, public download SHA-256 verified and queue drained to zero.
- Vercel Git import is building via the dashboard. The user handled its 2FA prompt; connector creation had returned 403.
- Actual Pi camera capture, Wi-Fi recovery, systemd permissions, power and enclosure checks require hardware access.

No admin/service-role key was obtained or placed on the Pi/site. `device/config.json` and `.env.local` are local ignored files. London Drift was not changed. No AI ranking or automatic cloud deletion was added.
