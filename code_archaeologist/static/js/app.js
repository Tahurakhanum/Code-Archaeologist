// Adds the Investigate, Timeline and PDF buttons to saved analysis detail pages.
(() => {
  const match = window.location.pathname.match(/^\/dashboard\/(\d+)$/);
  const header = document.querySelector('.dashboard > header');
  if (!match || !header) return;

  // Buttons go into .page-actions, in front of the Delete button.
  const actions = header.querySelector('.page-actions') || header;
  const addButton = (className, path, label, iconClass, icon) => {
    const link = document.createElement('a');
    link.className = className;
    link.href = `/dashboard/${match[1]}/${path}`;
    link.textContent = `${label} `;
    const iconElement = document.createElement('span');
    iconElement.className = iconClass;
    iconElement.textContent = icon;
    link.append(iconElement);
    actions.insertBefore(link, actions.querySelector('.danger-button'));
  };

  addButton('button', 'investigate', 'Investigate code', 'arrow', '→');
  addButton('button button-secondary', 'timeline', 'View timeline', 'arrow', '→');
  addButton('button button-secondary', 'report.pdf', 'Download PDF', 'arrow-down', '↓');
})();
