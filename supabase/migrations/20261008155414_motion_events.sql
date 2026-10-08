begin;
alter table public.captures
 add column trigger text not null default 'scheduled' check (trigger in ('scheduled','motion')),
 add column event_id uuid,
 add column motion_score double precision check (motion_score >= 0 and motion_score <= 1),
 add constraint capture_event_shape check (
   (trigger = 'scheduled' and event_id is null and motion_score is null)
   or (trigger = 'motion' and event_id is not null and motion_score is not null)
 );
grant insert (trigger,event_id,motion_score) on public.captures to authenticated;
create index captures_event_idx on public.captures(device_id,event_id) where event_id is not null;
commit;
