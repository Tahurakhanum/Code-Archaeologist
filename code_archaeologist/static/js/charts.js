// Draws the analysis dashboard charts with Chart.js.
// The data comes from the <script id="chart-data"> JSON block in detail.html.
// All colours are read from the CSS variables in app.css, so the theme stays in one place.
(() => {
  const dataElement = document.getElementById('chart-data');
  if (!dataElement || typeof Chart === 'undefined') return;
  const data = JSON.parse(dataElement.textContent);

  const css = getComputedStyle(document.documentElement);
  const token = (name) => css.getPropertyValue(name).trim();
  const BLUE = token('--blue');
  const VIOLET = token('--accent');
  const MUTED = token('--muted');
  const TEXT = token('--text');
  const SURFACE = token('--surface');
  const GRID = 'rgba(140, 170, 255, 0.07)';
  const MONO = token('--font-mono');
  // One distinct colour per contributor, assigned in a fixed order; "Other" is always grey.
  const SERIES_COLORS = [1, 2, 3, 4, 5].map((n) => token(`--chart-${n}`));
  const OTHER_COLOR = token('--chart-other');

  const reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;

  Chart.defaults.font.family = token('--font-body');
  Chart.defaults.color = MUTED;
  Chart.defaults.maintainAspectRatio = false;
  // Set single properties: replacing the whole object would break Chart.js's colour animation.
  Chart.defaults.animation.duration = reduceMotion ? 0 : 900;
  Chart.defaults.animation.easing = 'easeOutQuart';

  // Dark tooltips with monospaced numbers
  Object.assign(Chart.defaults.plugins.tooltip, {
    backgroundColor: 'rgba(10, 16, 32, 0.96)',
    borderColor: 'rgba(140, 170, 255, 0.24)',
    borderWidth: 1,
    cornerRadius: 10,
    padding: 12,
    titleColor: TEXT,
    bodyColor: TEXT,
    bodyFont: { family: MONO, size: 12 },
    titleFont: { family: token('--font-body'), size: 12, weight: '700' },
    boxPadding: 5,
  });

  const tickFont = { family: MONO, size: 10 };
  const integerAxis = { beginAtZero: true, ticks: { precision: 0, font: tickFont }, grid: { color: GRID }, border: { display: false } };
  const plainAxis = { ticks: { font: tickFont }, grid: { display: false }, border: { color: GRID } };

  // Long file paths are shortened on the axis; the tooltip shows the full path.
  const shortPath = (path) => {
    const parts = path.split('/');
    return parts.length > 2 ? '…/' + parts.slice(-2).join('/') : path;
  };

  // A blue-to-violet canvas gradient. The chart area is unknown until the first layout,
  // so Chart.js calls this as a "scriptable option" and we fall back to plain blue.
  const gradient = (direction) => ({ chart }) => {
    const { ctx, chartArea } = chart;
    if (!chartArea) return BLUE;
    const fill = direction === 'horizontal'
      ? ctx.createLinearGradient(chartArea.left, 0, chartArea.right, 0)
      : ctx.createLinearGradient(0, chartArea.bottom, 0, chartArea.top);
    fill.addColorStop(0, BLUE);
    fill.addColorStop(1, VIOLET);
    return fill;
  };

  // The soft area under the line: fades out towards the bottom.
  const areaFill = ({ chart }) => {
    const { ctx, chartArea } = chart;
    if (!chartArea) return 'transparent';
    const fill = ctx.createLinearGradient(0, chartArea.top, 0, chartArea.bottom);
    fill.addColorStop(0, 'rgba(99, 102, 241, 0.32)');
    fill.addColorStop(1, 'rgba(59, 130, 246, 0)');
    return fill;
  };

  // Plugin: adds a soft glow behind the bars and lines of single-colour charts.
  const glow = {
    id: 'glow',
    beforeDatasetDraw(chart) {
      chart.ctx.save();
      chart.ctx.shadowColor = 'rgba(99, 102, 241, 0.55)';
      chart.ctx.shadowBlur = 12;
    },
    afterDatasetDraw(chart) {
      chart.ctx.restore();
    },
  };

  // Plugin: a thin vertical line that marks the hovered point on the line chart.
  const crosshair = {
    id: 'crosshair',
    afterDatasetsDraw(chart) {
      const active = chart.tooltip && chart.tooltip.getActiveElements();
      if (!active || !active.length) return;
      const { ctx, chartArea } = chart;
      ctx.save();
      ctx.strokeStyle = 'rgba(140, 170, 255, 0.35)';
      ctx.lineWidth = 1;
      ctx.beginPath();
      ctx.moveTo(active[0].element.x, chartArea.top);
      ctx.lineTo(active[0].element.x, chartArea.bottom);
      ctx.stroke();
      ctx.restore();
    },
  };

  // Each chart is created when it scrolls into view, so its entrance animation is seen.
  const draw = (id, config) => {
    const canvas = document.getElementById(id);
    if (!canvas) return;
    if (!('IntersectionObserver' in window)) {
      new Chart(canvas, config);
      return;
    }
    const observer = new IntersectionObserver((entries) => {
      if (!entries.some((entry) => entry.isIntersecting)) return;
      observer.disconnect();
      new Chart(canvas, config);
    }, { rootMargin: '0px 0px -8% 0px' });
    observer.observe(canvas);
  };

  // 1. Commits over time (line chart)
  if (data.commit_activity) {
    draw('commitActivityChart', {
      type: 'line',
      plugins: [glow, crosshair],
      data: {
        labels: data.commit_activity.labels,
        datasets: [{
          label: 'Commits',
          data: data.commit_activity.counts,
          borderColor: gradient('horizontal'),
          backgroundColor: areaFill,
          fill: true,
          tension: 0.3,
          pointRadius: data.commit_activity.labels.length > 40 ? 0 : 3,
          pointHoverRadius: 5,
          pointBackgroundColor: token('--blue-2'),
          pointBorderColor: SURFACE,
          borderWidth: 2,
        }],
      },
      options: {
        interaction: { mode: 'index', intersect: false },
        plugins: { legend: { display: false } },
        scales: { y: integerAxis, x: { ...plainAxis, ticks: { ...plainAxis.ticks, maxTicksLimit: 12, autoSkip: true } } },
      },
    });
  }

  // 2. Commits per contributor (bar chart)
  if (data.contributors.length) {
    draw('contributorChart', {
      type: 'bar',
      plugins: [glow],
      data: {
        labels: data.contributors.map((c) => c.name),
        datasets: [{
          label: 'Commits',
          data: data.contributors.map((c) => c.commits),
          backgroundColor: gradient('vertical'),
          borderRadius: 4,
          maxBarThickness: 34,
        }],
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
          // A thin border in the card colour leaves a small gap between stacked segments.
          borderColor: SURFACE,
          borderWidth: 1,
          borderSkipped: false,
          maxBarThickness: 34,
        })),
      },
      options: {
        interaction: { mode: 'index', intersect: false },
        plugins: { legend: { position: 'bottom', labels: { boxWidth: 10, boxHeight: 10, useBorderRadius: true, borderRadius: 3, font: { size: 11 } } } },
        scales: {
          x: { ...plainAxis, stacked: true, ticks: { ...plainAxis.ticks, maxTicksLimit: 8, autoSkip: true } },
          y: { ...integerAxis, stacked: true },
        },
      },
    });
  }

  // 4. File modification frequency (horizontal bars)
  if (data.files.length) {
    draw('fileFrequencyChart', {
      type: 'bar',
      plugins: [glow],
      data: {
        labels: data.files.map((f) => shortPath(f.path)),
        datasets: [{
          label: 'Commits that changed this file',
          data: data.files.map((f) => f.changes),
          backgroundColor: gradient('horizontal'),
          borderRadius: 4,
          maxBarThickness: 22,
        }],
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
