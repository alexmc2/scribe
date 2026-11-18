// The sidebar's list of meetings: grouped by day, searchable, click to open.
// Meetings can be archived: kept, but listed apart under "Archived".

import { api, errorMessage } from './api.js';
import { ui } from './dom.js';
import { clockFormat, dayLabel, duration } from './format.js';
import { icon } from './icons.js';
import { closeSidebar } from './layout.js';
import { renderAll } from './render.js';
import { recordingOrPaused, store } from './state.js';
import { toast } from './toast.js';
import { renderTranscript } from './transcript.js';
import type { MeetingSummary, Session } from './types.js';

let reloadTimer = 0;

export function loadMeetingsSoon(delay = 250): void {
  clearTimeout(reloadTimer);
  reloadTimer = window.setTimeout(() => void loadMeetings(), delay);
}

export async function loadMeetings(): Promise<void> {
  try {
    const query = encodeURIComponent(ui.search.value.trim());
    const archived = store.showArchived;
    const answer = await api<{
      meetings: MeetingSummary[];
      archived_count: number;
    }>(`/api/meetings?q=${query}${archived ? '&archived=1' : ''}`);
    if (archived !== store.showArchived) return; // they switched lists meanwhile
    if (archived && !answer.archived_count) {
      // The last archived meeting was brought back: return to the full list.
      store.showArchived = false;
      return loadMeetings();
    }
    store.meetings = answer.meetings;
    store.archivedCount = answer.archived_count;
    renderMeetings();
  } catch {
    // The connection banner already explains this.
  }
}

/** A link-like button in the list, e.g. "Archived (3)" or "Back". */
function listButton(
  className: string,
  label: string,
  onClick: () => void,
): HTMLButtonElement {
  const button = document.createElement('button');
  button.type = 'button';
  button.className = className;
  button.textContent = label;
  button.addEventListener('click', onClick);
  return button;
}

function showArchived(show: boolean): void {
  store.showArchived = show;
  store.meetings = [];
  renderMeetings();
  void loadMeetings();
}

export function renderMeetings(): void {
  const groups = new Map<string, MeetingSummary[]>();
  for (const meeting of store.meetings) {
    const label = dayLabel(new Date(meeting.started_at));
    groups.set(label, [...(groups.get(label) ?? []), meeting]);
  }
  const nodes: HTMLElement[] = [];
  if (store.showArchived) {
    const head = document.createElement('div');
    head.className = 'list-head';
    const back = listButton('list-back', 'All meetings', () => {
      showArchived(false);
      ui.search.focus();
    });
    back.insertAdjacentHTML('afterbegin', icon('back', 'icon', 16));
    const label = document.createElement('h2');
    label.textContent = 'Archived';
    head.append(back, label);
    nodes.push(head);
  }
  for (const [label, meetings] of groups) {
    const heading = document.createElement('h2');
    heading.className = 'day';
    heading.textContent = label;
    nodes.push(heading, ...meetings.map(meetingItem));
  }
  if (!store.meetings.length) {
    const empty = document.createElement('p');
    empty.className = 'meetings-empty';
    empty.textContent = ui.search.value.trim()
      ? 'No meetings match that search.'
      : store.showArchived
        ? 'Archived meetings appear here.'
        : 'Past meetings appear here.';
    nodes.push(empty);
  }
  if (!store.showArchived && store.archivedCount) {
    nodes.push(
      listButton(
        'archived-link',
        `Archived (${store.archivedCount.toLocaleString()})`,
        () => showArchived(true),
      ),
    );
  }
  ui.meetings.replaceChildren(...nodes);
}

function meetingItem(meeting: MeetingSummary): HTMLElement {
  const item = document.createElement('button');
  item.type = 'button';
  item.className = 'meeting';
  const untitled =
    meeting.kind === 'notes' ? 'Untitled notes' : 'Untitled meeting';
  item.title = meeting.title || meeting.preview || untitled;
  item.dataset.id = meeting.id;
  item.setAttribute('aria-current', String(store.shown?.id === meeting.id));

  const title = document.createElement('span');
  title.className = meeting.title ? 'meeting-title' : 'meeting-title untitled';
  title.textContent = item.title;

  const meta = document.createElement('span');
  meta.className = 'meeting-meta';
  const started = clockFormat.format(new Date(meeting.started_at));
  const isLive = store.live?.id === meeting.id && recordingOrPaused();
  if (isLive) {
    const dot = document.createElement('span');
    dot.className = 'meeting-live';
    dot.setAttribute('aria-hidden', 'true');
    meta.append(
      dot,
      `${started}, ${store.engine?.state === 'paused' ? 'paused' : 'recording'}`,
    );
  } else {
    meta.append(`${started}, ${duration(meeting.duration)}`);
  }

  item.append(title, meta);
  item.addEventListener('click', () => void openMeeting(meeting.id));

  const wrapper = document.createElement('div');
  wrapper.className = 'meeting-item';
  wrapper.append(item);
  if (!isLive) {
    // Archive (or bring back) without opening it, from a button shown on hover.
    const archive = !meeting.archived;
    const action = document.createElement('button');
    action.type = 'button';
    action.className = 'meeting-action';
    action.title = archive ? 'Archive' : 'Unarchive';
    action.setAttribute(
      'aria-label',
      `${archive ? 'Archive' : 'Unarchive'} ${item.title}`,
    );
    action.innerHTML = icon(archive ? 'archive' : 'unarchive', 'icon', 16);
    action.addEventListener(
      'click',
      () => void archiveMeeting(meeting.id, archive),
    );
    wrapper.append(action);
  }
  return wrapper;
}

/** Archive a meeting or bring it back. It stays open if it's on screen. */
export async function archiveMeeting(
  id: string,
  archived: boolean,
  undoable = true,
): Promise<void> {
  try {
    await api<Session>(`/api/meetings/${id}/archive`, { archived });
  } catch (error) {
    toast(errorMessage(error), true);
    return;
  }
  for (const session of new Set([store.shown, store.live])) {
    if (session?.id === id) session.archived = archived;
  }
  // Take it off the list now rather than waiting for the reload.
  store.meetings = store.meetings.filter((m) => m.id !== id);
  store.archivedCount = Math.max(0, store.archivedCount + (archived ? 1 : -1));
  renderMeetings();
  renderAll();
  void loadMeetings();
  const undo = undoable
    ? { label: 'Undo', run: () => void archiveMeeting(id, !archived, false) }
    : undefined;
  toast(
    archived
      ? 'Archived. It’s kept under “Archived” at the end of the list.'
      : 'Back in the list of meetings.',
    false,
    undo,
  );
}

export async function openMeeting(id: string): Promise<void> {
  closeSidebar();
  if (store.live?.id === id) {
    store.shown = store.live;
  } else {
    try {
      store.shown = await api<Session>(`/api/meetings/${id}`);
    } catch (error) {
      toast(errorMessage(error), true);
      return;
    }
  }
  renderTranscript();
  renderAll();
  renderMeetings();
}

/** Take a deleted meeting off the screen, falling back to the live one. */
export function forgetMeeting(id: string): void {
  store.meetings = store.meetings.filter((m) => m.id !== id);
  if (store.live?.id === id) store.live = null;
  if (store.shown?.id === id) {
    store.shown = store.live;
    renderTranscript();
  }
  renderAll();
  renderMeetings();
}

export function initMeetings(): void {
  ui.search.addEventListener('input', () => loadMeetingsSoon(200));
}
