import assert from 'node:assert/strict';
import {validDate, formatCaptureLabel, getArchive} from '../lib/archive.js';
import {isLatestArchive, startArchiveRefresh} from '../lib/archive-refresh.js';
assert(validDate('2026-10-08'));
assert(!validDate('2026-02-30'));
assert(!validDate('2026-10-08&offset=999'));
delete process.env.SUPABASE_URL;
assert.equal((await getArchive()).status,'unconfigured');
process.env.SUPABASE_URL='https://example.supabase.co';
process.env.SUPABASE_PUBLISHABLE_KEY='test-publishable';
let observed;
global.fetch=async(url, options)=>{observed={url,options}; return {ok:true,json:async()=>Array.from({length:49},(_,i)=>({id:i,object_path:`device/${i}.jpg`,label:'fox',label_confidence:0.867}))};};
const result=await getArchive('2026-10-08',2);
assert.equal(result.captures.length,48); assert(result.hasMore);
const query=new URL(observed.url).searchParams;
assert.deepEqual(query.getAll('captured_at'),['gte.2026-10-08T00:00:00Z','lt.2026-10-09T00:00:00.000Z']);
assert.equal(query.get('offset'),'96');
assert.equal(observed.options.headers.apikey,'test-publishable');
assert(query.get('select').endsWith(',label,label_confidence'));
assert.equal(formatCaptureLabel(result.captures[0]), 'FOX · 87%');
assert.equal(formatCaptureLabel({label:'nothing', label_confidence:0.25}), 'NOTHING');
const requests=[];
global.fetch=async(url)=>{
  requests.push(new URL(url).searchParams);
  return requests.length === 1
    ? {ok:false,status:400,json:async()=>({code:'42703',message:'column captures.label does not exist'})}
    : {ok:true,json:async()=>[{id:1,object_path:'device/1.jpg',trigger:'motion'}]};
};
const legacy=await getArchive('2026-10-08',2);
assert.equal(legacy.status,'ready');
assert.equal(legacy.captures[0].trigger,'motion');
assert.equal(formatCaptureLabel(legacy.captures[0]),'');
assert.deepEqual(requests[1].getAll('captured_at'),query.getAll('captured_at'));
assert.equal(requests[1].get('offset'),'96');
assert.equal(requests[1].get('select'),'id,captured_at,object_path,is_mock,trigger,event_id');
let otherErrorRequests=0;
global.fetch=async()=>{
  otherErrorRequests++;
  return {ok:false,status:400,json:async()=>({code:'42703',message:'column captures.trigger does not exist'})};
};
assert.equal((await getArchive()).status,'error');
assert.equal(otherErrorRequests,1);
global.fetch=async()=>({ok:false});
assert.equal((await getArchive()).status,'error');
console.log('PASS: archive date validation, configuration, pagination, UTC boundaries and error states');
assert(isLatestArchive(undefined, 0));
assert(!isLatestArchive(undefined, 1));
assert(!isLatestArchive('2026-10-08', 0));
assert(!isLatestArchive('invalid', 0));
let tick, cleared, refreshes = 0;
const browser = {
  document: {visibilityState: 'visible'},
  setInterval(fn, delay) { tick = fn; assert.equal(delay, 60000); return 1; },
  clearInterval(id) { cleared = id; },
};
const stop = startArchiveRefresh(() => refreshes++, browser);
tick();
browser.document.visibilityState = 'hidden';
tick();
assert.equal(refreshes, 1);
stop();
assert.equal(cleared, 1);
console.log('PASS: only the latest unfiltered archive refreshes, every minute while visible');
