-- Apply once to a NEW dedicated project using the SQL editor, or move this into
-- a CLI-generated migration. No existing tables or policies are replaced.
begin;
create table public.camera_devices (
  id uuid primary key references auth.users(id),
  label text not null,
  enabled boolean not null default true
);
alter table public.camera_devices enable row level security;
revoke all on public.camera_devices from anon, authenticated;
grant select on public.camera_devices to authenticated;
create policy device_reads_own_registration on public.camera_devices for select to authenticated
using (id = (select auth.uid()));

create table public.captures (
  id uuid primary key,
  device_id uuid not null references public.camera_devices(id),
  captured_at timestamptz not null check (captured_at >= '2020-01-01'::timestamptz and captured_at <= now() + interval '10 minutes'),
  received_at timestamptz not null default now(),
  object_path text not null unique,
  sha256 text not null check (sha256 ~ '^[0-9a-f]{64}$'),
  bytes integer not null check (bytes > 0 and bytes <= 8388608),
  is_mock boolean not null default false,
  check (object_path = device_id::text || '/' || id::text || '.jpg')
);
create index captures_time_idx on public.captures(captured_at desc, id desc);
create index captures_device_idx on public.captures(device_id);
alter table public.captures enable row level security;
revoke all on public.captures from anon, authenticated;
grant select on public.captures to anon, authenticated;
grant insert (id, device_id, captured_at, object_path, sha256, bytes, is_mock) on public.captures to authenticated;
create policy archive_read on public.captures for select to anon, authenticated using (true);
create policy camera_insert on public.captures for insert to authenticated with check (
 device_id = (select auth.uid())
 and exists (select 1 from public.camera_devices d where d.id = (select auth.uid()) and d.enabled)
 and exists (select 1 from storage.objects o where o.bucket_id = 'backyard-images' and o.name = object_path)
);

-- The archive is public by design. Only registered devices may append JPEGs.
insert into storage.buckets(id, name, public, file_size_limit, allowed_mime_types)
values ('backyard-images','backyard-images',true,8388608,array['image/jpeg']);
create policy camera_object_insert on storage.objects for insert to authenticated with check (
 bucket_id = 'backyard-images'
 and name ~ ('^' || (select auth.uid())::text || '/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}[.]jpg$')
 and exists (select 1 from public.camera_devices d where d.id = (select auth.uid()) and d.enabled)
);
create policy camera_object_verify on storage.objects for select to authenticated using (
 bucket_id = 'backyard-images' and (storage.foldername(name))[1] = (select auth.uid())::text
 and exists (select 1 from public.camera_devices d where d.id = (select auth.uid()) and d.enabled)
);
-- Deliberately no UPDATE or DELETE policies. Device cannot replace an image.
commit;
