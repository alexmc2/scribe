// The top bar (status, recording buttons) and the meeting's title and details line.

import { api, errorMessage } from "./api.js";
import { ui } from "./dom.js";
import { clockFormat, duration, elapsedOf, fullDayFormat, offset, secondsFormat, wordCount } from "./format.js";
import { applySnapshot } from "./live.js";
import { openMeeting } from "./meetings.js";
import { renderFile } from "./panel.js";
import { recordingOrPaused, showingLive, store } from "./state.js";
import { act, toast } from "./toast.js";
import type { RecorderState, Session, Snapshot } from "./types.js";

const STATUS_LABELS: Record<RecorderState, string> = {
  loading: "Loading",
  ready: "Ready",
  recording: "Recording",
  paused: "Paused",
  error: "Can't record",
};

export function renderStatus(): void {
  const state = store.engine?.state ?? "loading";
  ui.app.dataset.state = state;
  ui.statusLabel.textContent = state === "ready" && store.live ? "Stopped" : STATUS_LABELS[state];
  ui.statusTime.textContent = store.live && recordingOrPaused() ? offset(elapsedOf(store.live)) : "";
  const title = store.shown?.title || "Untitled meeting";
  document.title = state === "recording" ? `● ${title} – Scribe` : store.shown ? `${title} – Scribe` : "Scribe";
}

const PRIMARY_LABELS: Partial<Record<RecorderState, string>> = {
  recording: "Pause",
  paused: "Resume",
  ready: "Start recording",
};

export function renderControls(): void {
  const primary = store.engine ? PRIMARY_LABELS[store.engine.state] : undefined;
  ui.primaryButton.hidden = !primary;
  ui.primaryButton.textContent = primary ?? "";
  ui.stopButton.hidden = !recordingOrPaused();
  ui.newButton.hidden = !recordingOrPaused();
  ui.backButton.hidden = showingLive() || !store.live || !recordingOrPaused();
  renderFile();
}

export function renderHeader(): void {
  const session = store.shown;
  ui.title.hidden = !session;
  if (document.activeElement !== ui.title) ui.title.value = session?.title ?? "";
  renderMeta();
}

/** The line under the title: when the meeting was, and when it was last saved. */
export function renderMeta(): void {
  const session = store.shown;
  ui.meta.replaceChildren();
  if (!session) return;
  const started = new Date(session.started_at);
  const when = fullDayFormat.format(started);
  if (showingLive() && recordingOrPaused()) {
    ui.meta.append(`${when}. Started at ${clockFormat.format(started)}.`);
  } else {
    const ended = session.ended_at ? ` to ${clockFormat.format(new Date(session.ended_at))}` : "";
    ui.meta.append(
      `${when}, ${clockFormat.format(started)}${ended} (${duration(elapsedOf(session))}). ` +
        `${wordCount(session).toLocaleString()} words.`,
    );
  }
  const engine = store.engine;
  if (!showingLive() || !engine) return;
  if (engine.save_error) {
    const failed = document.createElement("span");
    failed.className = "save-failed";
    failed.textContent = ` ${engine.save_error}`;
    ui.meta.append(failed);
  } else if (engine.last_saved) {
    ui.meta.append(` Saved at ${secondsFormat.format(new Date(engine.last_saved))}.`);
  }
}

export function renderBanner(): void {
  let message = "";
  if (!store.connected) message = "Lost contact with Scribe. Check it's still running in the terminal. Reconnecting…";
  else if (store.engine?.input_error) message = store.engine.input_error;
  ui.banner.textContent = message;
  ui.banner.hidden = !message;
}

function recordingAction(action: "start" | "pause" | "resume" | "stop"): () => Promise<void> {
  return async () => applySnapshot(await api<Snapshot>(`/api/recording/${action}`, {}));
}

async function saveTitle(): Promise<void> {
  const session = store.shown;
  if (!session || ui.title.value.trim() === session.title) return;
  try {
    const updated = await api<Session>(`/api/meetings/${session.id}/title`, { title: ui.title.value });
    for (const s of [store.shown, store.live]) {
      if (s?.id === updated.id) {
        s.title = updated.title;
        s.path = updated.path;
      }
    }
    renderStatus();
    renderFile();
  } catch (error) {
    toast(`Couldn't rename the meeting: ${errorMessage(error)}`, true);
  }
}

const PRIMARY_ACTIONS: Partial<Record<RecorderState, "pause" | "resume" | "start">> = {
  recording: "pause",
  paused: "resume",
  ready: "start",
};

export function initHeader(): void {
  ui.primaryButton.addEventListener("click", () => {
    const action = store.engine ? PRIMARY_ACTIONS[store.engine.state] : undefined;
    if (!action) return;
    if (action === "start") store.shown = null; // show the new meeting when it starts
    void act(ui.primaryButton, recordingAction(action));
  });
  ui.emptyButton.addEventListener("click", () => void act(ui.emptyButton, recordingAction("start")));
  ui.stopButton.addEventListener("click", () => void act(ui.stopButton, recordingAction("stop")));
  ui.newButton.addEventListener("click", () => {
    store.shown = null;
    void act(ui.newButton, recordingAction("start"));
  });
  ui.backButton.addEventListener("click", () => {
    if (store.live) void openMeeting(store.live.id);
  });

  ui.title.addEventListener("change", () => void saveTitle());
  ui.title.addEventListener("keydown", (event) => {
    if (event.key === "Enter") ui.title.blur();
    if (event.key === "Escape") {
      ui.title.value = store.shown?.title ?? "";
      ui.title.blur();
    }
  });
}
