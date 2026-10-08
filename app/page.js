import {getArchive, validDate} from '../lib/archive';
export const dynamic = 'force-dynamic';
const display = value => new Intl.DateTimeFormat('en-GB', {dateStyle:'long', timeZone:'UTC'}).format(new Date(value));
export default async function Page({searchParams}) {
  const params = await searchParams;
  const date = validDate(params.date) ? params.date : undefined;
  const page = /^\d{1,5}$/.test(params.page || '') ? Number(params.page) : 0;
  const {status, captures, hasMore} = await getArchive(date, page);
  const days = Object.groupBy(captures, c => c.captured_at.slice(0,10));
  const pageUrl = n => `/?${new URLSearchParams({...date && {date}, page: String(n)})}`;
  return <main>
    <header><a className="brand" href="/">BACKYARD CAMERA</a><span className="edition">FIELD NOTES / 001</span></header>
    <section className="intro"><p className="eyebrow">AN OBSERVATION IN FIVE-MINUTE INTERVALS</p><h1>A place,<br/><em>over time.</em></h1><p className="description">The light shifts. The weather passes. A small camera stays still, making a photographic record of the everyday.</p></section>
    <section aria-label="Photo archive">
      <div className="toolbar"><h2>The archive</h2><form><label htmlFor="date">Day <span>(UTC)</span></label><input id="date" type="date" name="date" defaultValue={date}/><button type="submit">View</button>{date && <a href="/">All days</a>}</form></div>
      {params.date && !date && <p role="alert">That date is invalid. Showing all days.</p>}
      {status === 'unconfigured' && <div className="empty"><span className="frame">＋</span><h3>Waiting for the first photograph.</h3><p>The archive is ready to connect. Cloud setup is still in progress.</p></div>}
      {status === 'error' && <div className="empty" role="alert"><h3>The archive is temporarily unavailable.</h3><p>Please try again shortly.</p><a href="/">Try again</a></div>}
      {status === 'ready' && !captures.length && <div className="empty"><h3>No photographs {date ? 'on this day' : 'yet'}.</h3><p>New captures will appear here after upload.</p></div>}
      {Object.entries(days).map(([day, images]) => <section className="day" key={day}><h3>{display(day)}</h3><div className="grid">{images.map((c, i) => <figure key={c.id}><a href={c.url} target="_blank" rel="noreferrer"><img src={c.url} alt={`Fixed backyard view, ${display(c.captured_at)} at ${c.captured_at.slice(11,16)} UTC${c.is_mock ? ' — mock capture' : ''}`} loading={i === 0 ? 'eager' : 'lazy'}/></a><figcaption><time dateTime={c.captured_at}>{c.captured_at.slice(11,16)} UTC</time><span>{c.is_mock ? 'MOCK CAPTURE' : 'FIVE-MINUTE STUDY'}</span></figcaption></figure>)}</div></section>)}
      <nav className="pagination" aria-label="Archive pages">{page > 0 && <a href={pageUrl(page-1)}>← Newer</a>}{hasMore && <a href={pageUrl(page+1)}>Older →</a>}</nav>
    </section>
    <footer><span>One camera. One view. Always changing.</span><span>Captured every 5 minutes · Times in UTC</span></footer>
  </main>;
}
