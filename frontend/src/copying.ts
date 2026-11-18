// Copying the transcript: one paragraph from the button beside it, or all of
// it from "Copy all" in the top bar (and "Copy text" in the details panel).
// Text is read from the page, so a correction still being saved is included.
// Selecting text by hand and copying it gives the same text. Notes copy as
// the words alone; a meeting's paragraphs keep their times and speakers.

import { errorMessage } from './api.js';
import { copyToClipboard } from './clipboard.js';
import { child, ui } from './dom.js';
import { plainText, tidy } from './format.js';
import { icon } from './icons.js';
import { shownKind } from './state.js';
import { toast } from './toast.js';

/** A paragraph as plainText() takes it, with ``text`` the words to copy. */
function paragraph(row: HTMLElement, text: string) {
  const speaker = child(row, '.speaker');
  return {
    time: tidy(child(row, '.stamp').textContent),
    speaker: speaker.hidden ? '' : tidy(speaker.textContent),
    text,
  };
}

/** The shown transcript as it reads on screen. */
export function transcriptText(): string {
  return plainText(
    [...ui.rows.querySelectorAll<HTMLElement>('.row')].map((row) =>
      paragraph(row, tidy(child(row, '.words').textContent)),
    ),
    shownKind(),
  );
}

export async function copyTranscript(): Promise<void> {
  const text = transcriptText();
  if (!text) {
    toast('Nothing to copy yet.');
    return;
  }
  try {
    await copyToClipboard(text);
    toast(shownKind() === 'notes' ? 'Notes copied.' : 'Transcript copied.');
  } catch (error) {
    toast(errorMessage(error), true);
  }
}

const copiedTimers = new WeakMap<HTMLElement, number>();

/** Copy one paragraph, and tick its button for a moment to say so. */
async function copyParagraph(button: HTMLElement): Promise<void> {
  const row = button.closest<HTMLElement>('.row');
  const text = row ? tidy(child(row, '.words').textContent) : '';
  if (!text) return;
  try {
    await copyToClipboard(text);
  } catch (error) {
    toast(errorMessage(error), true);
    return;
  }
  button.innerHTML = icon('check', 'icon', 16);
  button.classList.add('copied');
  button.setAttribute('aria-label', 'Copied');
  clearTimeout(copiedTimers.get(button));
  copiedTimers.set(
    button,
    window.setTimeout(() => {
      button.innerHTML = icon('copy', 'icon', 16);
      button.classList.remove('copied');
      button.setAttribute('aria-label', 'Copy paragraph');
    }, 1500),
  );
}

/** The part of a paragraph's words that lies inside a selection. */
function selectedWords(row: HTMLElement, selection: Range): string {
  const words = document.createRange();
  words.selectNodeContents(child(row, '.words'));
  if (selection.compareBoundaryPoints(Range.START_TO_START, words) > 0)
    words.setStart(selection.startContainer, selection.startOffset);
  if (selection.compareBoundaryPoints(Range.END_TO_END, words) < 0)
    words.setEnd(selection.endContainer, selection.endOffset);
  return tidy(words.toString());
}

/** Selecting across paragraphs and copying gives what "Copy all" would for
 * that part, rather than the page's layout ("0:23", "You", then the words). */
function copySelection(event: ClipboardEvent): void {
  const selection = document.getSelection();
  if (!selection || selection.isCollapsed || !event.clipboardData) return;
  if ((event.target as Element).closest?.('input, textarea')) return;
  const range = selection.getRangeAt(0);
  const rows = [...ui.rows.querySelectorAll<HTMLElement>('.row')].filter(
    (row) => !row.hidden && range.intersectsNode(row),
  );
  if (!rows.length) return;
  const [only] = rows;
  const within = (node: Node) =>
    rows.length === 1 && !!only && child(only, '.words').contains(node);
  // Inside one paragraph's words, the browser already copies the right thing.
  if (within(range.startContainer) && within(range.endContainer)) return;
  const text = plainText(
    rows.map((row) => paragraph(row, selectedWords(row, range))),
    shownKind(),
  );
  if (!text) return;
  event.clipboardData.setData('text/plain', text);
  event.preventDefault();
}

export function initCopying(): void {
  document.addEventListener('copy', copySelection);
  ui.rows.addEventListener('click', (event) => {
    const button = (event.target as Element).closest<HTMLElement>(
      '[data-tool="copy"]',
    );
    if (button) void copyParagraph(button);
  });
  ui.copyAllButton.addEventListener('click', () => void copyTranscript());
}
