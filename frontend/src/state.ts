// Everything the page knows, in one place. Modules read and update this and
// then call the render functions for the parts of the page that changed.

import type {
  Block,
  Kind,
  MeetingSummary,
  Session,
  Snapshot,
} from './types.js';

export interface Editing {
  id: number; // block id
  base: string; // the text when editing began, so the server can merge late speech
  words: HTMLElement;
  sessionId: string;
}

export const store = {
  engine: null as Snapshot | null, // the recorder's state, from the server
  live: null as Session | null, // the current meeting: recording, paused, or just stopped
  shown: null as Session | null, // the meeting on screen: the live one or a past one
  preview: '',
  meetings: [] as MeetingSummary[],
  showArchived: false, // the sidebar lists archived meetings instead
  archivedCount: 0,
  editing: null as Editing | null, // the paragraph being edited
  deferred: new Map<number, Block>(), // updates to a paragraph that arrived while it was being edited
  connected: false,
  follow: true, // keep the newest text in view
};

export function recordingOrPaused(): boolean {
  const state = store.engine?.state;
  return state === 'recording' || state === 'paused';
}

export function showingLive(): boolean {
  return Boolean(store.shown && store.live && store.shown.id === store.live.id);
}

/** Whether the page reads as a meeting or as notes: what the shown recording
 * is, or with nothing shown, what the next recording will be. */
export function shownKind(): Kind {
  return store.shown?.kind ?? store.engine?.settings.kind ?? 'meeting';
}

export function blockById(id: number): Block | undefined {
  return store.shown?.blocks.find((block) => block.id === id);
}

/** Put a new or changed block into a session's list. */
export function upsert(session: Session, block: Block): void {
  const index = session.blocks.findIndex((b) => b.id === block.id);
  if (index >= 0) session.blocks[index] = block;
  else session.blocks.push(block);
}
