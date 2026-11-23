export function isLatestArchive(date, page) {
  return !date && page === 0;
}

export function startArchiveRefresh(refresh, browser = globalThis) {
  const timer = browser.setInterval(() => {
    if (browser.document.visibilityState === 'visible') refresh();
  }, 60000);
  return () => browser.clearInterval(timer);
}
