export function validDate(value) {
  return typeof value === 'string' && /^\d{4}-\d{2}-\d{2}$/.test(value) &&
    Number.isFinite(Date.parse(value)) && new Date(value).toISOString().slice(0, 10) === value;
}
export async function getArchive(date, page = 0) {
  const base = process.env.SUPABASE_URL;
  const key = process.env.SUPABASE_PUBLISHABLE_KEY;
  if (!base || !key) return {status: 'unconfigured', captures: []};
  const query = new URLSearchParams({select: 'id,captured_at,object_path,is_mock,trigger,event_id', order: 'captured_at.desc,id.desc', limit: '49', offset: String(page * 48)});
  if (date) {
    query.append('captured_at', `gte.${date}T00:00:00Z`);
    query.append('captured_at', `lt.${new Date(Date.parse(date) + 86400000).toISOString()}`);
  }
  try {
    const response = await fetch(`${base}/rest/v1/captures?${query}`, {headers: {apikey: key}, cache: 'no-store', signal: AbortSignal.timeout(10000)});
    if (!response.ok) throw new Error(`Archive returned ${response.status}`);
    const captures = await response.json();
    return {status: 'ready', hasMore: captures.length > 48, captures: captures.slice(0, 48).map(c => ({...c, url: `${base}/storage/v1/object/public/backyard-images/${c.object_path.split('/').map(encodeURIComponent).join('/')}`}))};
  } catch {
    return {status: 'error', captures: []};
  }
}
