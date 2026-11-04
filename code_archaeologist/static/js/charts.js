// Draws the analysis dashboard charts with Chart.js.
// The data comes from the <script id="chart-data"> JSON block in detail.html.
(() => {
  const dataElement = document.getElementById('chart-data');
  if (!dataElement || typeof Chart === 'undefined') return;
  const data = JSON.parse(dataElement.textContent);

  const ACCENT = '#6558e8';
  // One distinct colour per contributor; "Other contributors" is always grey.
  const SERIES_COLORS = ['#6558e8', '#1baf7a', '#eb6834', '#2c8be0', '#d4a01d'];
  const OTHER_COLOR = '#b8bfcc';
  const MUTED = '#667085';
  const GRID = '#eef0f4';

  Chart.defaults.font.family = getComputedStyle(document.body).fontFamily;
  Chart.defaults.color = MUTED;
  Chart.defaults.maintainAspectRatio = false;

  const integerAxis = { beginAtZero: true, ticks: { precision: 0 }, grid: { color: GRID } };
  const plainAxis = { grid: { display: false } };

  // Long file paths are shortened on the axis; the tooltip shows the full path.
  const shortPath = (path) => {
    const parts = path.split('/');
    return parts.length > 2 ? '…/' + parts.slice(-2).join('/') : path;
  };

  const draw = (id, config) => {
    const canvas = document.getElementById(id);
    if (canvas) new Chart(canvas, config);
  };

  // 1. Commits over time (line chart)
  if (data.commit_activity) {
    draw('commitActivityChart', {
      type: 'line',
      data: {
        labels: data.commit_activity.labels,
        datasets: [{
          label: 'Commits',
          data: data.commit_activity.counts,
          borderColor: ACCENT,
          backgroundColor: 'rgba(101, 88, 232, 0.12)',
          fill: true,
          tension: 0.25,
          pointRadius: data.commit_activity.labels.length > 40 ? 0 : 3,
          borderWidth: 2,
        }],
      },
      options: {
        interaction: { mode: 'index', intersect: false },
        plugins: { legend: { display: false } },
        scales: { y: integerAxis, x: { ...plainAxis, ticks: { maxTicksLimit: 12, autoSkip: true } } },
      },
    });
  }

  // 2. Commits per contributor (bar chart)
  if (data.contributors.length) {
    draw('contributorChart', {
      type: 'bar',
      data: {
        labels: data.contributors.map((c) => c.name),
        datasets: [{ label: 'Commits', data: data.contributors.map((c) => c.commits), backgroundColor: ACCENT, borderRadius: 4 }],
      },
      options: { plugins: { legend: { display: false } }, scales: { y: integerAxis, x: plainAxis } },
    });
  }

  // 3. Contributor activity over time (stacked bars, one colour per contributor)
  if (data.contributor_activity) {
    draw('contributorActivityChart', {
      type: 'bar',
      data: {
        labels: data.contributor_activity.labels,
        datasets: data.contributor_activity.series.map((series, index) => ({
          label: series.name,
          data: series.counts,
          backgroundColor: series.name === 'Other contributors' ? OTHER_COLOR : SERIES_COLORS[index % SERIES_COLORS.length],
        })),
      },
      options: {
        interaction: { mode: 'index', intersect: false },
        plugins: { legend: { position: 'bottom', labels: { boxWidth: 12 } } },
        scales: {
          x: { ...plainAxis, stacked: true, ticks: { maxTicksLimit: 8, autoSkip: true } },
          y: { ...integerAxis, stacked: true },
        },
      },
    });
  }

  // 4. File modification frequency (horizontal bars)
  if (data.files.length) {
    draw('fileFrequencyChart', {
      type: 'bar',
      data: {
        labels: data.files.map((f) => shortPath(f.path)),
        datasets: [{ label: 'Commits that changed this file', data: data.files.map((f) => f.changes), backgroundColor: ACCENT, borderRadius: 4 }],
      },
      options: {
        indexAxis: 'y',
        plugins: {
          legend: { display: false },
          tooltip: { callbacks: { title: (items) => data.files[items[0].dataIndex].path } },
        },
        scales: { x: integerAxis, y: plainAxis },
      },
    });
  }
})();
