// Progressive enhancement for saved analysis detail pages.
(() => {
  const match = window.location.pathname.match(/^\/dashboard\/(\d+)$/);
  const header = document.querySelector('.dashboard > header');
  if (!match || !header) return;
  const link = document.createElement('a');
  link.className = 'button';
  link.href = `/dashboard/${match[1]}/investigate`;
  link.textContent = 'Investigate code →';
  header.append(link);
  const timeline = document.createElement('a');
  timeline.className = 'button';
  timeline.href = `/dashboard/${match[1]}/timeline`;
  timeline.textContent = 'View timeline →';
  header.append(timeline);
  const report = document.createElement('a');
  report.className = 'button';
  report.href = `/dashboard/${match[1]}/report.pdf`;
  report.textContent = 'Download PDF ↓';
  header.append(report);
})();
