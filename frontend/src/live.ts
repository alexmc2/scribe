// Live updates from the server over server-sent events (/api/events).

import { renderBanner, renderMeta } from "./header.js";
import { inputsLoaded, loadInputs, setLevels } from "./inputs.js";
import { forgetMeeting, loadMeetings, loadMeetingsSoon, renderMeetings } from "./meetings.js";
import { renderFile } from "./panel.js";
import { renderAll } from "./render.js";
import { showingLive, store, upsert } from "./state.js";
import { renderEmpty, renderJump, renderPreview, renderTranscript, showBlock } from "./transcript.js";
import type { ServerEvents, Snapshot } from "./types.js";

/** Take in the recorder's whole state, following the live meeting if it's on screen. */
export function applySnapshot(snapshot: Snapshot): void {
  const followLive = showingLive() || !store.shown;
  const previousLiveId = store.live?.id;
  store.engine = snapshot;
  store.live = snapshot.session;
  store.preview = snapshot.preview || "";
  if (followLive) {
    store.shown = store.live;
    renderTranscript();
  } else if (store.live && store.live.id !== previousLiveId) {
    loadMeetingsSoon(0);
  }
  renderAll();
  renderMeetings();
}

type Handlers = { [K in keyof ServerEvents]: (data: ServerEvents[K]) => void };

const handlers: Handlers = {
  snapshot(data) {
    const firstConnect = !store.engine;
    applySnapshot(data);
    void loadMeetings();
    if (firstConnect || !inputsLoaded()) void loadInputs();
  },
  state(data) {
    if (!store.engine) return;
    const wasRecording = store.engine.state === "recording";
    Object.assign(store.engine, data);
    if (wasRecording && data.state !== "recording") store.preview = "";
    renderAll();
    renderJump();
    renderMeetings();
  },
  session({ session }) {
    const followLive = showingLive() || !store.shown;
    store.live = session;
    if (followLive) {
      store.shown = session;
      renderTranscript();
    }
    renderAll();
  },
  block({ session_id, block }) {
    for (const session of new Set([store.live, store.shown])) {
      if (session?.id === session_id) upsert(session, block);
    }
    if (store.shown?.id === session_id) showBlock(block);
  },
  preview({ session_id, text }) {
    if (store.live?.id !== session_id) return;
    store.preview = text;
    renderPreview();
    renderEmpty();
  },
  saved({ session_id, at, path }) {
    if (store.live?.id !== session_id || !store.engine) return;
    store.engine.last_saved = at;
    store.engine.save_error = null;
    store.live.path = path;
    renderMeta();
    renderFile();
  },
  save_failed({ session_id, message }) {
    if (store.live?.id !== session_id || !store.engine) return;
    store.engine.save_error = message;
    renderMeta();
  },
  levels({ levels }) {
    setLevels(levels);
  },
  meetings_changed() {
    loadMeetingsSoon();
  },
  deleted({ session_id }) {
    forgetMeeting(session_id);
  },
};

export function connect(): void {
  const events = new EventSource("/api/events");
  for (const [kind, handle] of Object.entries(handlers) as [keyof ServerEvents, (data: unknown) => void][]) {
    events.addEventListener(kind, (event) => handle(JSON.parse((event as MessageEvent<string>).data)));
  }
  // EventSource reconnects by itself; the server then sends a fresh snapshot.
  events.addEventListener("open", () => {
    store.connected = true;
    renderBanner();
  });
  events.addEventListener("error", () => {
    store.connected = false;
    renderBanner();
  });
}
