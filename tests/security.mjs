import {PGlite} from '@electric-sql/pglite';
import {readFileSync} from 'node:fs';
import assert from 'node:assert/strict';
const db = new PGlite();
await db.exec(`create role anon; create role authenticated; create role service_role bypassrls; create schema auth; create schema storage;
create table auth.users(id uuid primary key);
create function auth.uid() returns uuid language sql stable as $$ select nullif(current_setting('request.jwt.claim.sub',true),'')::uuid $$;
create table storage.buckets(id text primary key,name text,public boolean,file_size_limit bigint,allowed_mime_types text[]);
create table storage.objects(id uuid default gen_random_uuid(),bucket_id text,name text);
alter table storage.objects enable row level security;
create function storage.foldername(text) returns text[] language sql immutable as $$ select string_to_array($1,'/') $$;
grant usage on schema auth,storage,public to anon,authenticated;
grant select,insert,update,delete on storage.objects to authenticated;`);
await db.exec(readFileSync(new URL('../supabase/migrations/20261008152618_backyard_camera.sql',import.meta.url),'utf8'));
await db.exec(readFileSync(new URL('../supabase/migrations/20261008155414_motion_events.sql',import.meta.url),'utf8'));
await db.exec(readFileSync(new URL('../supabase/migrations/20261008160000_capture_labels.sql',import.meta.url),'utf8'));
const a='11111111-1111-4111-8111-111111111111', b='22222222-2222-4222-8222-222222222222', id='aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa';
await db.exec(`insert into auth.users values ('${a}'),('${b}'); insert into camera_devices values ('${a}','test',true);`);
const asRole = async(role,uid,sql) => {
  await db.exec(`set role ${role}; select set_config('request.jwt.claim.sub','${uid}',false);`);
  try {return await db.query(sql);} finally {await db.exec('reset role');}
};
const insert = (device=a,captureId=id) => `insert into captures(id,device_id,captured_at,object_path,sha256,bytes) values ('${captureId}','${device}',now(),'${device}/${captureId}.jpg','${'a'.repeat(64)}',10)`;
await assert.rejects(asRole('authenticated',a,insert()), /row-level security/);
await assert.rejects(asRole('authenticated',b,`insert into storage.objects(bucket_id,name) values ('backyard-images','${b}/${id}.jpg')`), /row-level security/);
await assert.rejects(asRole('authenticated',a,`insert into storage.objects(bucket_id,name) values ('backyard-images','${b}/${id}.jpg')`), /row-level security/);
await asRole('authenticated',a,`insert into storage.objects(bucket_id,name) values ('backyard-images','${a}/${id}.jpg')`);
await asRole('authenticated',a,insert());
assert.equal((await asRole('anon','',`select * from captures`)).rows.length,1);
await assert.rejects(asRole('anon','',insert()), /permission denied/);
await assert.rejects(asRole('authenticated',a,`update captures set bytes=20`), /permission denied/);
await assert.rejects(asRole('authenticated',a,`delete from captures`), /permission denied/);
assert.equal((await asRole('authenticated',a,`delete from storage.objects returning *`)).rows.length,0);
assert.equal((await asRole('authenticated',a,`update storage.objects set name='changed' returning *`)).rows.length,0);
await db.exec(`update camera_devices set enabled=false where id='${a}'`);
await assert.rejects(asRole('authenticated',a,`insert into storage.objects(bucket_id,name) values ('backyard-images','${a}/bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb.jpg')`), /row-level security/);
console.log('PASS: SQL schema + 11 privilege/RLS checks (local Postgres engine; Storage HTTP not simulated)');
await db.exec(`update camera_devices set enabled=true where id='${a}'`);
for (const [column,value] of [['label',"'person'"],['label_confidence','0.9'],['label_model',"'test'"],['label_attempts','1'],['label_visibility',"'needs_review'"]]) {
  await assert.rejects(asRole('authenticated',a,`insert into captures(${column}) values (${value})`), /permission denied/);
  await assert.rejects(asRole('authenticated',a,`update captures set ${column}=${value}`), /permission denied/);
}
const {rows:[{expected}]} = await db.query(`select to_jsonb(c) - array['received_at','label','label_confidence','label_model','label_attempts','label_visibility'] as expected from captures c`);
const verify = metadata => `select verify_hidden_capture('${JSON.stringify(metadata)}'::jsonb) as verified`;
for (const visibility of ['needs_review','false_trigger']) {
  await asRole('service_role','',`update captures set label='person',label_confidence=0.9,label_model='test',label_visibility='${visibility}'`);
  for (const [role,uid] of [['anon',''],['authenticated',a],['authenticated',b]]) {
    assert.equal((await asRole(role,uid,'select * from captures')).rows.length,0);
  }
  assert.equal((await asRole('service_role','','select * from captures')).rows.length,1);
}
await assert.rejects(asRole('anon','',verify(expected)), /permission denied/);
assert.equal((await asRole('authenticated',a,verify(expected))).rows[0].verified,true);
assert.equal((await asRole('authenticated',a,verify({...expected,bytes:11}))).rows[0].verified,false);
assert.equal((await asRole('authenticated',b,verify(expected))).rows[0].verified,false);
await asRole('service_role','',`update captures set label_visibility='visible'`);
assert.equal((await asRole('anon','','select label from captures')).rows[0].label,'person');
console.log('PASS: capture label permissions, hidden rows, owner release, and device duplicate verification');
await db.close();
