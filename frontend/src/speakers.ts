// Naming who spoke. Clicking a paragraph's speaker tag (or "Add who said
// this") swaps in a small text box; Enter or clicking away saves, Escape
// cancels. Renaming a voice such as "Others" then offers to rename it
// everywhere in the meeting, which also names the speech still to come.

import { api, errorMessage } from './api.js';
import { child, ui } from './dom.js';
import { tidy } from './format.js';
import { blockById, store, upsert } from './state.js';
import { toast } from './toast.js';
import { fillSpeaker, showBlock } from './transcript.js';
import type { Block } from './types.js';

interface Naming {
  id: number; // block id
  sessionId: string;
  before: string; // the name when naming began; '' for none
  row: HTMLElement;
  input: HTMLInputElement;
}

let naming: Naming | null = null;

/** Names already used in the shown meeting, offered as suggestions. */
function fillSuggestions(): void {
  const names = new Set<string>();
  for (const block of store.shown?.blocks ?? []) {
    if (block.speaker && block.text) names.add(block.speaker);
  }
  names.add('You');
  ui.speakerNames.replaceChildren(
    ...[...names].map((name) => {
      const option = document.createElement('option');
      option.value = name;
      return option;
    }),
  );
}

function startNaming(row: HTMLElement): void {
  const session = store.shown;
  const block = blockById(Number(row.dataset.id));
  if (!session || !block) return;
  if (naming) void commitNaming();
  const input = document.createElement('input');
  input.className = 'speaker-input';
  input.type = 'text';
  input.value = block.speaker ?? '';
  input.placeholder = 'Name';
  input.maxLength = 60;
  input.autocomplete = 'off';
  input.spellcheck = false;
  input.setAttribute('list', ui.speakerNames.id);
  input.setAttribute('aria-label', 'Who said this');
  input.addEventListener('keydown', (event) => {
    if (event.key === 'Enter') {
      event.preventDefault();
      void commitNaming();
    } else if (event.key === 'Escape') {
      event.preventDefault();
      cancelNaming();
    }
  });
  input.addEventListener('blur', () => void commitNaming());
  fillSuggestions();
  naming = {
    id: block.id,
    sessionId: session.id,
    before: block.speaker ?? '',
    row,
    input,
  };
  row.classList.add('naming');
  child(row, '.speaker').after(input);
  input.focus();
  input.select();
}

/** Put the speaker tag back in place of the text box. */
function stopNaming(): Naming | null {
  const current = naming;
  if (!current) return null;
  naming = null;
  current.row.classList.remove('naming');
  const hadFocus = document.activeElement === current.input;
  current.input.remove(); // may fire blur, which finds nothing left to save
  if (hadFocus && current.row.isConnected) {
    // Keep keyboard users where they were, rather than at the top of the page.
    const speaker = child<HTMLButtonElement>(current.row, '.speaker');
    (speaker.hidden
      ? child<HTMLButtonElement>(current.row, '[data-tool="name"]')
      : speaker
    ).focus({ preventScroll: true });
  }
  return current;
}

export function cancelNaming(): void {
  stopNaming();
}

/** Take in changed paragraphs from the server and show them. */
function apply(sessionId: string, blocks: Block[]): void {
  for (const block of blocks) {
    for (const session of new Set([store.shown, store.live])) {
      if (session?.id === sessionId) upsert(session, block);
    }
    if (store.shown?.id === sessionId) showBlock(block);
  }
}

async function commitNaming(): Promise<void> {
  const current = stopNaming();
  if (!current) return;
  const name = tidy(current.input.value);
  const { id, sessionId, before, row } = current;
  if (name === before) return;
  fillSpeaker(row, name || null); // show it straight away
  let block: Block;
  try {
    block = await api<Block>(
      `/api/meetings/${sessionId}/blocks/${id}/speaker`,
      {
        name,
      },
    );
  } catch (error) {
    toast(`Couldn't change who said this: ${errorMessage(error)}`, true);
    if (row.isConnected) fillSpeaker(row, before || null);
    return;
  }
  apply(sessionId, [block]);
  offerRenameAll(sessionId, before, name);
}

/** After naming one paragraph, offer to rename the rest by the same speaker. */
function offerRenameAll(sessionId: string, before: string, name: string): void {
  const session = store.shown?.id === sessionId ? store.shown : null;
  if (!session || !before || !name) return;
  const rest = session.blocks.filter(
    (b) => b.speaker === before && b.text,
  ).length;
  if (!rest) return;
  const paragraphs = rest === 1 ? 'paragraph says' : 'paragraphs say';
  toast(
    `Changed to “${name}”. ${rest} more ${paragraphs} “${before}”.`,
    false,
    {
      label: 'Change all',
      run: () => void renameAll(sessionId, before, name),
    },
  );
}

async function renameAll(
  sessionId: string,
  before: string,
  name: string,
): Promise<void> {
  try {
    const { blocks } = await api<{ blocks: Block[] }>(
      `/api/meetings/${sessionId}/speakers`,
      { from: before, to: name },
    );
    apply(sessionId, blocks);
    toast(`Everything said by “${before}” is now “${name}”.`);
  } catch (error) {
    toast(`Couldn't rename “${before}”: ${errorMessage(error)}`, true);
  }
}

export function initSpeakers(): void {
  ui.rows.addEventListener('click', (event) => {
    const target = event.target as Element;
    const button = target.closest('.speaker, [data-tool="name"]');
    const row = button?.closest<HTMLElement>('.row');
    if (row) startNaming(row);
  });
}
