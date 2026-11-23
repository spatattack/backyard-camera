export function validDate(value) {
  return typeof value === 'string' && /^\d{4}-\d{2}-\d{2}$/.test(value) &&
    Number.isFinite(Date.parse(value)) && new Date(value).toISOString().slice(0, 10) === value;
}
export function formatCaptureLabel(capture) {
  if (!capture.label) return '';
  const label = capture.label.toUpperCase();
  return capture.label === 'nothing' ? label : `${label} · ${Math.round(capture.label_confidence * 100)}%`;
}
export async function getArchive(date, page = 0) {
  const base = process.env.SUPABASE_URL;
  const key = process.env.SUPABASE_PUBLISHABLE_KEY;
  if (!base || !key) return {status: 'unconfigured', captures: []};
  const columns = 'id,captured_at,object_path,is_mock,trigger,event_id';
  const query = new URLSearchParams({select: columns + ',label,label_confidence', order: 'captured_at.desc,id.desc', limit: '49', offset: String(page * 48)});
  if (date) {
    query.append('captured_at', `gte.${date}T00:00:00Z`);
    query.append('captured_at', `lt.${new Date(Date.parse(date) + 86400000).toISOString()}`);
  }
  try {
    const request = () => fetch(`${base}/rest/v1/captures?${query}`, {headers: {apikey: key}, cache: 'no-store', signal: AbortSignal.timeout(10000)});
    let response = await request();
    if (!response.ok && response.status === 400) {
      const problem = await response.json();
      if (problem.code === '42703' && /\bcaptures\.label(?:_confidence)?\b/.test(problem.message)) {
        query.set('select', columns);
        response = await request();
      }
    }
    if (!response.ok) throw new Error(`Archive returned ${response.status}`);
    const captures = await response.json();
    return {status: 'ready', hasMore: captures.length > 48, captures: captures.slice(0, 48).map(c => ({...c, url: `${base}/storage/v1/object/public/backyard-images/${c.object_path.split('/').map(encodeURIComponent).join('/')}`}))};
  } catch {
    return {status: 'error', captures: []};
  }
}
