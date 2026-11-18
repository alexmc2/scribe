// Typed handles on the page's fixed elements (see scribe/web/index.html).

export function byId<T extends HTMLElement = HTMLElement>(id: string): T {
  const element = document.getElementById(id);
  if (!element) throw new Error(`The page is missing #${id}`);
  return element as T;
}

/** The first descendant matching a selector; it must exist. */
export function child<T extends Element = HTMLElement>(
  parent: ParentNode,
  selector: string,
): T {
  const element = parent.querySelector<T>(selector);
  if (!element) throw new Error(`Missing ${selector}`);
  return element;
}

export const ui = {
  app: byId('app'),
  sidebar: byId('sidebar'),
  sidebarToggle: byId<HTMLButtonElement>('sidebarToggle'),
  sidebarClose: byId<HTMLButtonElement>('sidebarClose'),
  search: byId<HTMLInputElement>('search'),
  meetings: byId('meetings'),
  folderButton: byId<HTMLButtonElement>('folderButton'),

  main: byId('main'),
  chrome: byId('chrome'),
  statusLabel: byId('statusLabel'),
  statusTime: byId('statusTime'),
  listening: byId('listening'),
  primaryButton: byId<HTMLButtonElement>('primaryButton'),
  stopButton: byId<HTMLButtonElement>('stopButton'),
  newButton: byId<HTMLButtonElement>('newButton'),
  backButton: byId<HTMLButtonElement>('backButton'),
  copyAllButton: byId<HTMLButtonElement>('copyAllButton'),
  banner: byId('banner'),

  scroller: byId('scroller'),
  sheet: byId('sheet'),
  title: byId<HTMLInputElement>('title'),
  meta: byId('meta'),
  rows: byId('rows'),
  speakerNames: byId<HTMLDataListElement>('speakerNames'),
  liveRow: byId('liveRow'),
  preview: byId('preview'),
  empty: byId('empty'),
  emptyText: byId('emptyText'),
  emptyButton: byId<HTMLButtonElement>('emptyButton'),
  jumpButton: byId<HTMLButtonElement>('jumpButton'),

  panel: byId('panel'),
  panelToggle: byId<HTMLButtonElement>('panelToggle'),
  panelClose: byId<HTMLButtonElement>('panelClose'),
  vocabForm: byId<HTMLFormElement>('vocabForm'),
  vocabText: byId<HTMLTextAreaElement>('vocabText'),
  vocabSave: byId<HTMLButtonElement>('vocabSave'),
  tidyToggle: byId<HTMLInputElement>('tidyToggle'),
  kindPicker: byId('kindPicker'),
  kindHint: byId('kindHint'),
  fileSection: byId('fileSection'),
  filePath: byId('filePath'),
  archiveButton: byId<HTMLButtonElement>('archiveButton'),
  deleteButton: byId<HTMLButtonElement>('deleteButton'),
  deleteConfirm: byId('deleteConfirm'),
  deleteCancel: byId<HTMLButtonElement>('deleteCancel'),
  deleteYes: byId<HTMLButtonElement>('deleteYes'),
  engine: byId('engine'),

  scrim: byId('scrim'),
  toast: byId('toast'),
};
