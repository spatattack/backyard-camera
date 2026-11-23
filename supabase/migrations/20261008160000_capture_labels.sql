begin;

alter table public.captures
 add column label text check (label in (
   'person','bird','cat','dog','fox','squirrel','hedgehog','other animal','vehicle','nothing'
 )),
 add column label_confidence double precision check (label_confidence >= 0 and label_confidence <= 1),
 add column label_model text,
 add column label_attempts integer not null default 0 check (label_attempts >= 0),
 add column label_visibility text not null default 'visible'
   check (label_visibility in ('visible','needs_review','false_trigger')),
 add constraint capture_label_shape check (
   (label is null and label_confidence is null and label_model is null)
   or (label is not null and label_confidence is not null and label_model is not null)
 );

create index captures_unlabelled_idx on public.captures(label_attempts,received_at,id)
 where label is null;

drop policy archive_read on public.captures;
create policy archive_read on public.captures for select to anon, authenticated
using (label_visibility = 'visible');
grant select, update (label,label_confidence,label_model,label_attempts,label_visibility)
 on public.captures to service_role;

create function public.verify_hidden_capture(expected jsonb) returns boolean
language sql stable security definer set search_path = ''
as $$
 select exists (
   select 1 from public.captures c
   join public.camera_devices d on d.id = c.device_id and d.enabled
   where c.id = (expected->>'id')::uuid
     and c.device_id = (select auth.uid())
     and c.label_visibility <> 'visible'
     and c.captured_at = (expected->>'captured_at')::timestamptz
     and jsonb_build_object('id',c.id,'device_id',c.device_id,'object_path',c.object_path,
         'sha256',c.sha256,'bytes',c.bytes,'is_mock',c.is_mock,'trigger',c.trigger,
         'event_id',c.event_id,'motion_score',c.motion_score) = (expected - 'captured_at')
 );
$$;
revoke all on function public.verify_hidden_capture(jsonb) from public, anon, authenticated;
grant execute on function public.verify_hidden_capture(jsonb) to authenticated;

commit;
