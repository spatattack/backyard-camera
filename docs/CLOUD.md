# Cloud configuration

Use a dedicated Backyard Camera project; do not apply this schema to London Drift. The setup is additive but creates fixed table/bucket names and should be applied exactly once.

## 1. Supabase

1. Create `Backyard Camera` in your chosen organization. Choose London (`eu-west-2`) if offered. Review the displayed plan/cost. Keep the standard Postgres engine and Data API enabled. Save the database password privately; the app and device do not need it.
2. Run `supabase/migrations/20261008152618_backyard_camera.sql` in the project's SQL Editor. Alternatively use Supabase CLI migration tooling against this dedicated project. Do not run both paths.
3. Check `camera_devices`, `captures`, the `backyard-images` bucket and their RLS policies. The bucket is PUBLIC because this product is a public archive; only registered devices may write.
4. In Authentication → Users → Add user, create a dedicated device user with a long unique password and Auto Confirm enabled. Do not use your personal account password. No invitation or email needs to be sent. Copy its UUID.
5. Register that UUID in SQL Editor:

```sql
insert into public.camera_devices(id, label)
values ('REPLACE_WITH_AUTH_USER_UUID', 'Backyard Pi 3 A+');
```

6. Copy the project URL and **publishable** API key from the project connection/API settings. The device config needs these plus its own email and password. The website needs only URL + publishable key.
7. A dedicated project does not need public signups. Disable new user signups in Auth settings if enabled; the registration table still denies uploads to any unregistered user.

## 2. First mock upload

Set real values in `device/config.json`, then:

```sh
chmod 600 device/config.json
python3 device/camera.py --config device/config.json --mock device/mock.jpg --once
python3 device/camera.py --config device/config.json --status
```

Expect an `Uploaded` log and `pending: 0`. In Supabase, check that the object exists and that the matching `captures` row has `is_mock = true`. A file alone is not sufficient: the metadata insert must also succeed. Re-run `--upload-only` after any outage; the client checks duplicate objects and rows rather than overwriting them.

## 3. Website + GitHub + Vercel

Create an empty private `spatattack/backyard-camera` repository. Push this directory as the repository root (not its parent). No secrets are committed. Import that repository in Vercel; choose Next.js, root `./`, Node 22 or newer, build `npm run build`.

Set these for Production and Preview in Vercel:

| Variable | Value | Secret? |
|---|---|---|
| `SUPABASE_URL` | Dedicated project's HTTPS URL | No |
| `SUPABASE_PUBLISHABLE_KEY` | `sb_publishable_...` | Public API credential, protected by RLS |

Do not add a service-role key or device password. Deploy and open the resulting URL. Confirm the mock JPEG loads and is labelled MOCK CAPTURE. Filter by its UTC date. GitHub pushes will trigger Vercel deployments once the Git integration is connected; GitHub Actions runs build/tests independently. Configure a required check/branch protection if desired.

## 4. Revocation and recovery

Disable a lost device immediately:

```sql
update public.camera_devices set enabled = false
where id = 'REPLACE_WITH_AUTH_USER_UUID';
```

This blocks new writes even with an unexpired JWT. Existing public images remain public. Then revoke its Auth sessions and change its device password before enabling it again. A Pi has no administrator credential to compromise.

For first-upload errors: confirm project URL/key, auto-confirmed device user, UUID registration, enabled flag, applied schema, JPEG size, UTC clock, and storage quota. The client deliberately omits detailed auth bodies from logs to avoid exposing secrets. Test authentication in the Supabase dashboard if needed.

## Verification boundary

The local security tests use PGlite with small `auth` and `storage` schema fixtures. They test PostgreSQL grants, RLS and constraints, not Supabase's Auth or Storage HTTP implementation. A live mock upload + object download + metadata query + rendered image is still required before calling the cloud flow verified.
