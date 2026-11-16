// Copying the transcript: one paragraph from the button beside it, or all of
// it from "Copy all" in the top bar (and "Copy text" in the details panel).
// Text is read from the page, so a correction still being saved is included.

import { errorMessage } from './api.js';
import { copyToClipboard } from './clipboard.js';
import { child, ui } from './dom.js';
import { plainText, tidy } from './format.js';
import { icon } from './icons.js';
import { toast } from './toast.js';

/** The shown transcript as it reads on screen. */
export function transcriptText(): string {
  return plainText(
    [...ui.rows.querySelectorAll<HTMLElement>('.row')].map((row) => {
      const speaker = child(row, '.speaker');
      return {
        speaker: speaker.hidden ? '' : tidy(speaker.textContent),
        text: tidy(child(row, '.words').textContent),
      };
    }),
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
    toast('Transcript copied.');
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

export function initCopying(): void {
  ui.rows.addEventListener('click', (event) => {
    const button = (event.target as Element).closest<HTMLElement>(
      '[data-tool="copy"]',
    );
    if (button) void copyParagraph(button);
  });
  ui.copyAllButton.addEventListener('click', () => void copyTranscript());
}
