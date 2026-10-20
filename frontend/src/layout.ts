// Page-level layout: the theme switch, the details panel (a collapsible column
// on wide windows, a drawer on narrow ones), and the sidebar drawer.

import { ui } from './dom.js';
import { pickers } from './inputs.js';

type Theme = 'system' | 'light' | 'dark';

/** localStorage can throw (private windows, blocked storage); the page must still work. */
function remember(key: string, value: string | null): void {
  try {
    if (value === null) localStorage.removeItem(key);
    else localStorage.setItem(key, value);
  } catch {
    // The choice still applies until the page closes.
  }
}

function recall(key: string): string | null {
  try {
    return localStorage.getItem(key);
  } catch {
    return null;
  }
}

function applyTheme(choice: Theme): void {
  if (choice === 'system') delete document.documentElement.dataset.theme;
  else document.documentElement.dataset.theme = choice;
  for (const button of document.querySelectorAll<HTMLElement>(
    '[data-theme-choice]',
  )) {
    button.setAttribute(
      'aria-checked',
      String(button.dataset.themeChoice === choice),
    );
  }
}

// On narrow windows the sidebar and the panel slide in over the transcript.
function setDrawer(
  drawer: HTMLElement,
  toggle: HTMLElement,
  open: boolean,
): void {
  drawer.classList.toggle('open', open);
  toggle.setAttribute('aria-expanded', String(open));
  ui.scrim.hidden =
    !ui.sidebar.classList.contains('open') &&
    !ui.panel.classList.contains('open');
}

export function closeSidebar(): void {
  setDrawer(ui.sidebar, ui.sidebarToggle, false);
}

function closeDrawers(): void {
  setDrawer(ui.sidebar, ui.sidebarToggle, false);
  setDrawer(ui.panel, ui.panelToggle, false);
  syncPanelToggle();
}

// Matches the breakpoint in css/layout.css.
const wideLayout = window.matchMedia('(min-width: 1181px)');

function panelVisible(): boolean {
  return wideLayout.matches
    ? document.documentElement.dataset.panel !== 'collapsed'
    : ui.panel.classList.contains('open');
}

function syncPanelToggle(): void {
  const open = panelVisible();
  ui.panelToggle.setAttribute('aria-expanded', String(open));
  ui.panelToggle.title = open ? 'Hide details' : 'Show details';
}

function setPanel(open: boolean): void {
  if (wideLayout.matches) {
    // The collapsed state lives on <html> so the page's first paint can use it (see index.html).
    if (open) delete document.documentElement.dataset.panel;
    else document.documentElement.dataset.panel = 'collapsed';
    remember('scribe-panel', open ? null : 'collapsed');
  } else {
    setDrawer(ui.sidebar, ui.sidebarToggle, false);
    setDrawer(ui.panel, ui.panelToggle, open);
  }
  syncPanelToggle();
}

/** The transcript is padded by the floating top bar's height, which changes when it wraps. */
function trackChromeHeight(): void {
  const update = () =>
    ui.main.style.setProperty('--chrome-height', `${ui.chrome.offsetHeight}px`);
  new ResizeObserver(update).observe(ui.chrome);
  update();
}

export function initLayout(): void {
  trackChromeHeight();

  for (const button of document.querySelectorAll<HTMLElement>(
    '[data-theme-choice]',
  )) {
    button.addEventListener('click', () => {
      const choice = (button.dataset.themeChoice ?? 'system') as Theme;
      remember('scribe-theme', choice === 'system' ? null : choice);
      applyTheme(choice);
    });
  }
  const saved = recall('scribe-theme');
  applyTheme(saved === 'light' || saved === 'dark' ? saved : 'system');

  ui.sidebarToggle.addEventListener('click', () => {
    setDrawer(ui.panel, ui.panelToggle, false);
    setDrawer(
      ui.sidebar,
      ui.sidebarToggle,
      !ui.sidebar.classList.contains('open'),
    );
  });
  ui.panelToggle.addEventListener('click', () => setPanel(!panelVisible()));
  ui.panelClose.addEventListener('click', () => {
    setPanel(false);
    ui.panelToggle.focus();
  });
  ui.scrim.addEventListener('click', closeDrawers);
  wideLayout.addEventListener('change', closeDrawers);
  syncPanelToggle();

  // Clicking elsewhere closes an open picker; Escape closes the drawers.
  document.addEventListener('click', (event) => {
    for (const picker of pickers()) {
      if (!picker.root.contains(event.target as Node)) picker.close();
    }
  });
  document.addEventListener('keydown', (event) => {
    if (event.key === 'Escape') closeDrawers();
  });
}
