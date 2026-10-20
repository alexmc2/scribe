// Correcting paragraphs. Each paragraph's text is a contenteditable span;
// focusing it starts an edit, leaving it saves, Escape cancels.

import { api, errorMessage } from './api.js';
import { ui } from './dom.js';
import { blockById, store, upsert } from './state.js';
import { toast } from './toast.js';
import { fillRow } from './transcript.js';
import type { Block } from './types.js';

function startEdit(words: HTMLElement): void {
  if (store.editing?.words === words || !store.shown) return;
  const row = words.closest<HTMLElement>('.row');
  const block = row && blockById(Number(row.dataset.id));
  if (!block) return;
  store.editing = {
    id: block.id,
    base: block.text,
    words,
    sessionId: store.shown.id,
  };
  words.spellcheck = true; // only underline spelling in the paragraph being edited
}

/** Put the caret at the point clicked, or at the end if that isn't in the text. */
function placeCaret(element: HTMLElement, event: MouseEvent): void {
  const selection = window.getSelection();
  if (!selection) return;
  let range: Range | null = null;
  if (document.caretPositionFromPoint) {
    const position = document.caretPositionFromPoint(
      event.clientX,
      event.clientY,
    );
    if (position) {
      range = document.createRange();
      range.setStart(position.offsetNode, position.offset);
    }
  } else if (document.caretRangeFromPoint) {
    range = document.caretRangeFromPoint(event.clientX, event.clientY);
  }
  if (!range || !element.contains(range.startContainer)) {
    range = document.createRange();
    range.selectNodeContents(element);
    range.collapse(false);
  }
  selection.removeAllRanges();
  selection.addRange(range);
}

function finishEditing() {
  const editing = store.editing!;
  store.editing = null;
  editing.words.spellcheck = false;
  const pending = store.deferred.get(editing.id);
  store.deferred.delete(editing.id);
  return { editing, pending };
}

export function cancelEdit(): void {
  if (!store.editing) return;
  const { editing, pending } = finishEditing();
  const block = pending ?? blockById(editing.id);
  const row = editing.words.closest<HTMLElement>('.row');
  if (block && row) fillRow(row, block);
}

async function commitEdit(): Promise<void> {
  if (!store.editing) return;
  const text = (store.editing.words.textContent ?? '')
    .replace(/\s+/g, ' ')
    .trim();
  const { editing, pending } = finishEditing();
  const row = editing.words.closest<HTMLElement>('.row');
  if (text === editing.base) {
    if (pending && row) fillRow(row, pending);
    return;
  }
  try {
    const block = await api<Block>(
      `/api/meetings/${editing.sessionId}/blocks/${editing.id}`,
      {
        text,
        base: editing.base, // lets the server keep speech that arrived while typing
      },
    );
    for (const session of [store.shown, store.live]) {
      if (session?.id === editing.sessionId) upsert(session, block);
    }
    if (row && store.shown?.id === editing.sessionId) fillRow(row, block);
  } catch (error) {
    toast(`Couldn't save the edit: ${errorMessage(error)}`, true);
    const block = pending ?? blockById(editing.id);
    if (block && row) fillRow(row, block);
  }
}

export function initEditing(): void {
  // A click anywhere in a paragraph's box (between lines, after the last word,
  // on the speaker tag) puts the caret in its text, at the nearest spot.
  ui.rows.addEventListener('mousedown', (event) => {
    const target = event.target as Element;
    const text = target.closest('.text');
    if (!text || target.closest('.words') || event.button !== 0) return;
    const words = text.querySelector<HTMLElement>('.words');
    if (!words) return;
    event.preventDefault();
    words.focus();
    placeCaret(words, event);
  });

  ui.rows.addEventListener('focusin', (event) => {
    const words = (event.target as Element).closest<HTMLElement>('.words');
    if (words) startEdit(words);
  });

  ui.rows.addEventListener('focusout', (event) => {
    if (store.editing && event.target === store.editing.words)
      void commitEdit();
  });

  ui.rows.addEventListener('keydown', (event) => {
    const words = (event.target as Element).closest<HTMLElement>('.words');
    if (!words || !store.editing) return;
    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault();
      words.blur(); // saves
    } else if (event.key === 'Escape') {
      event.preventDefault();
      cancelEdit();
      words.blur();
    }
  });
}
