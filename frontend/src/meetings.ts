// The sidebar's list of meetings: grouped by day, searchable, click to open.

import { api, errorMessage } from "./api.js";
import { ui } from "./dom.js";
import { clockFormat, dayLabel, duration } from "./format.js";
import { closeSidebar } from "./layout.js";
import { renderAll } from "./render.js";
import { recordingOrPaused, store } from "./state.js";
import { toast } from "./toast.js";
import { renderTranscript } from "./transcript.js";
import type { MeetingSummary, Session } from "./types.js";

let reloadTimer = 0;

export function loadMeetingsSoon(delay = 250): void {
  clearTimeout(reloadTimer);
  reloadTimer = window.setTimeout(() => void loadMeetings(), delay);
}

export async function loadMeetings(): Promise<void> {
  try {
    const query = encodeURIComponent(ui.search.value.trim());
    store.meetings = (await api<{ meetings: MeetingSummary[] }>(`/api/meetings?q=${query}`)).meetings;
    renderMeetings();
  } catch {
    // The connection banner already explains this.
  }
}

export function renderMeetings(): void {
  const groups = new Map<string, MeetingSummary[]>();
  for (const meeting of store.meetings) {
    const label = dayLabel(new Date(meeting.started_at));
    groups.set(label, [...(groups.get(label) ?? []), meeting]);
  }
  const nodes: HTMLElement[] = [];
  for (const [label, meetings] of groups) {
    const heading = document.createElement("h2");
    heading.className = "day";
    heading.textContent = label;
    nodes.push(heading, ...meetings.map(meetingItem));
  }
  if (!nodes.length) {
    const empty = document.createElement("p");
    empty.className = "meetings-empty";
    empty.textContent = ui.search.value.trim() ? "No meetings match that search." : "Past meetings appear here.";
    nodes.push(empty);
  }
  ui.meetings.replaceChildren(...nodes);
}

function meetingItem(meeting: MeetingSummary): HTMLElement {
  const item = document.createElement("button");
  item.type = "button";
  item.className = "meeting";
  item.dataset.id = meeting.id;
  item.setAttribute("aria-current", String(store.shown?.id === meeting.id));

  const title = document.createElement("span");
  title.className = meeting.title ? "meeting-title" : "meeting-title untitled";
  title.textContent = meeting.title || meeting.preview || "Untitled meeting";

  const meta = document.createElement("span");
  meta.className = "meeting-meta";
  const started = clockFormat.format(new Date(meeting.started_at));
  const isLive = store.live?.id === meeting.id && recordingOrPaused();
  if (isLive) {
    const dot = document.createElement("span");
    dot.className = "meeting-live";
    dot.setAttribute("aria-hidden", "true");
    meta.append(dot, `${started}, ${store.engine?.state === "paused" ? "paused" : "recording"}`);
  } else {
    meta.append(`${started}, ${duration(meeting.duration)}`);
  }

  item.append(title, meta);
  item.addEventListener("click", () => void openMeeting(meeting.id));
  return item;
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
  ui.search.addEventListener("input", () => loadMeetingsSoon(200));
}
