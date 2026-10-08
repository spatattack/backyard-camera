# Backyard Camera

A Raspberry Pi 3 A+ / Camera Module 3 records one still every five minutes. A small Next.js site presents the photographs by day. No AI ranking is required for the first version.

## Start on your Mac (no account or camera needed)

Requires Node.js 22+ and Python 3.9+. From this folder:

```sh
npm ci
python3 -m venv .venv
.venv/bin/pip install -r device/requirements-motion.txt
.venv/bin/python -m unittest discover -s tests -v
npm run test:security
npm run test:archive
python3 device/camera.py --config device/config.example.json --mock device/mock.jpg --once --offline
python3 device/camera.py --config device/config.example.json --status
npm run dev
```

Open http://localhost:3000. The site honestly shows that cloud configuration is missing; offline captures remain in `queue/`. `device/mock.jpg` is a synthetic sky/ground colour test, not a real backyard photograph. Use any JPEG up to 8 MiB with `--mock /path/to/photo.jpg`.

## Motion capture

Motion-triggered bursts, ignored regions, a cooldown and video replay are now available. See [Motion setup and testing](docs/MOTION.md). Scheduled-only mode remains available.

## Connect the cloud

Follow [Cloud setup](docs/CLOUD.md), then [Hardware bring-up](docs/HARDWARE.md). See [Verification and delivery status](docs/STATUS.md) for what has actually been tested/deployed.

```sh
cp .env.example .env.local
# Fill SUPABASE_URL and SUPABASE_PUBLISHABLE_KEY in .env.local.
cp device/config.example.json device/config.json
chmod 600 device/config.json
# Fill project URL, publishable key and the DEVICE account credentials.
python3 device/camera.py --config device/config.json --upload-only
python3 device/camera.py --config device/config.json --mock device/mock.jpg --once
npm run dev
```

Device config is ignored by Git. Never put a service-role/admin key on the Pi, in this repository, or in the website.

## How it works

1. `rpicam-still` autofocuses and captures a 2304×1296 JPEG at quality 85.
2. Python commits image bytes + UUID + UTC capture time + SHA-256 to SQLite (WAL, full synchronous writes).
3. A separate upload thread signs in as a dedicated Supabase Auth user, sends the image, then inserts metadata. It renews login before token expiry and backs off on failures.
4. Only after both operations succeed is the local item removed. UUID paths and duplicate verification make lost-response retries safe.
5. The Next.js server uses a publishable key to read metadata. The public JPEG bucket supplies images. Dates and pagination use UTC; every uploaded image appears, including clearly labelled mock captures.

The device can insert into its own folder only if its database registration is enabled. It cannot update/delete objects or metadata, register other devices, or read private account data. Public images and capture metadata are intentionally readable by anyone. Place the camera accordingly before starting real capture.

## Limits and operations

- Default interval 300 seconds; missed captures are not fabricated after shutdown.
- Queue budget 2 GiB, free-space reserve 256 MiB. At capacity, skip new photos rather than deleting pending ones. SQLite reuses freed pages; the database file may remain at its high-water size.
- A single process lock prevents two camera instances on one queue. Upload and capture use separate SQLite connections.
- Maximum file size 8 MiB. No automatic cloud deletion or retention policy. At 500 KB per photo, 288/day is about 144 MB/day; review the project's actual storage/egress quota before leaving it unattended for weeks.
- A permanently invalid oldest item blocks upload until investigated; it is preserved, never silently discarded. Fix clock/config/auth/quota errors, then use `--upload-only`. Back up the queue before manual repair.
- The Pi needs correct network-synchronised time. Captures more than 10 minutes in the future are rejected.
- Public anonymous reads are deliberate; there is no admin interface, AI scoring, daily winner, person recognition or continuous video recording in this MVP.

## Repository layout

- `device/`: standard-library Python capture/uploader, sample config, mock JPEG, systemd unit.
- `supabase/migrations/`: additive, one-time database and Storage policies.
- `app/`, `lib/`: Next.js archive.
- `tests/`: queue/retry tests, RLS tests on a local PostgreSQL engine, archive tests.
- `.github/workflows/check.yml`: build and checks; Vercel's Git integration deploys the web app.

## References

- [Raspberry Pi camera software](https://www.raspberrypi.com/documentation/computers/camera_software.html)
- [Supabase Storage access control](https://supabase.com/docs/guides/storage/security/access-control)
- [Supabase row-level security](https://supabase.com/docs/guides/database/postgres/row-level-security)
- [Vercel GitHub integration](https://vercel.com/docs/git/vercel-for-github)
