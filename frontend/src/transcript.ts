// The transcript: one row per paragraph, the live preview line, and keeping
// the newest text in view while recording.

import { child, ui } from './dom.js';
import { cancelEdit } from './editing.js';
import { offset, secondsFormat } from './format.js';
import { showingLive, store } from './state.js';
import type { Block } from './types.js';

function blockRow(block: Block): HTMLElement {
  const row = document.createElement('div');
  row.className = 'row';
  row.dataset.id = String(block.id);
  const stamp = document.createElement('time');
  stamp.className = 'stamp';
  const text = document.createElement('p');
  text.className = 'text';
  const speaker = document.createElement('span');
  speaker.className = 'speaker';
  // Every paragraph is always editable, so clicking, selecting and placing the
  // caret behave like any text box. Editing "starts" when it gets focus.
  const words = document.createElement('span');
  words.className = 'words';
  try {
    words.contentEditable = 'plaintext-only';
  } catch {
    words.contentEditable = 'true'; // browsers without plaintext-only
  }
  words.spellcheck = false;
  words.setAttribute('role', 'textbox');
  words.setAttribute('aria-label', `Paragraph at ${offset(block.start)}`);
  text.append(speaker, words);
  row.append(stamp, text);
  fillRow(row, block);
  return row;
}

export function fillRow(row: HTMLElement, block: Block): void {
  const stamp = child<HTMLTimeElement>(row, 'time');
  const speaker = child(row, '.speaker');
  const words = child(row, '.words');
  stamp.textContent = offset(block.start);
  if (store.shown) {
    const at = new Date(
      new Date(store.shown.started_at).getTime() + block.start * 1000,
    );
    stamp.dateTime = at.toISOString();
    stamp.title = secondsFormat.format(at);
  }
  speaker.textContent = block.speaker ?? '';
  speaker.hidden = !block.speaker;
  words.textContent = block.text;
  row.hidden = !block.text; // a paragraph cleared by the user is gone
}

/** Rebuild every row, e.g. after switching meetings. */
export function renderTranscript(): void {
  cancelEdit();
  ui.rows.replaceChildren(...(store.shown?.blocks ?? []).map(blockRow));
  renderEmpty();
  renderPreview();
  if (showingLive()) {
    store.follow = true;
    scrollToEnd();
  } else {
    ui.scroller.scrollTop = 0;
  }
  renderJump();
}

/** Add or update one paragraph as speech arrives. */
export function showBlock(block: Block): void {
  if (store.editing?.id === block.id) {
    store.deferred.set(block.id, block); // applied when they finish editing
    return;
  }
  const existing = ui.rows.querySelector<HTMLElement>(
    `.row[data-id="${block.id}"]`,
  );
  if (existing) {
    fillRow(existing, block);
  } else {
    const row = blockRow(block);
    row.classList.add('flash');
    ui.rows.append(row);
  }
  renderEmpty();
  scrollToEnd();
}

export function renderEmpty(): void {
  const engine = store.engine;
  const session = store.shown;
  let message = '';
  let offerStart = false;
  if (!engine || engine.state === 'loading') {
    message = engine?.message || 'Loading the speech model…';
  } else if (engine.state === 'error') {
    message = engine.message;
  } else if (!session) {
    message = engine.message || 'Start recording to begin a new transcript.';
    offerStart = engine.state === 'ready';
  } else if (!session.blocks.some((b) => b.text)) {
    if (showingLive() && engine.state === 'recording') {
      message = store.preview
        ? ''
        : "Listening. Speech appears here as it's transcribed.";
    } else if (showingLive() && engine.state === 'paused') {
      message = 'Paused. Resume to keep recording.';
    } else {
      message = 'Nothing was transcribed in this meeting.';
    }
  }
  ui.emptyText.textContent = message;
  ui.empty.hidden = !message;
  ui.emptyButton.hidden = !offerStart;
}

/** The faint line at the end showing words still being worked out. */
export function renderPreview(): void {
  const live = showingLive() && store.engine?.state === 'recording';
  ui.liveRow.hidden = !live;
  ui.preview.textContent = live ? store.preview : '';
  if (live) scrollToEnd();
}

function scrollToEnd(): void {
  if (store.follow && showingLive())
    ui.scroller.scrollTop = ui.scroller.scrollHeight;
}

export function renderJump(): void {
  ui.jumpButton.hidden =
    store.follow || !showingLive() || store.engine?.state !== 'recording';
}

export function initTranscript(): void {
  // Scrolling up to reread stops the auto-scroll until they come back down.
  ui.scroller.addEventListener(
    'scroll',
    () => {
      const distance =
        ui.scroller.scrollHeight -
        ui.scroller.scrollTop -
        ui.scroller.clientHeight;
      store.follow = distance < 80;
      renderJump();
      // Frost the top bar only once text is underneath it.
      ui.main.classList.toggle('scrolled', ui.scroller.scrollTop > 0);
    },
    { passive: true },
  );
  ui.jumpButton.addEventListener('click', () => {
    store.follow = true;
    scrollToEnd();
    renderJump();
  });
}
