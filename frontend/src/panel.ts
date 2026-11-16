// The details panel: names and terms, tidying up speech, the transcript file
// (export, download, archive, delete) and which model is running.

import { api } from './api.js';
import { copyTranscript } from './copying.js';
import { ui } from './dom.js';
import { homePath } from './format.js';
import { renderPickers, setLevels } from './inputs.js';
import { archiveMeeting, forgetMeeting } from './meetings.js';
import { recordingOrPaused, store } from './state.js';
import { act, toast } from './toast.js';
import type { Session } from './types.js';

/** Model status, saved input choices, names and terms, and tidying. */
export function renderSettings(): void {
  const engine = store.engine;
  if (!engine) return;
  ui.engine.replaceChildren();
  if (engine.model) {
    // One span, so the flex gap after the status dot doesn't split the sentence.
    const text = document.createElement('span');
    const where = document.createElement('span');
    where.textContent =
      engine.device === 'cuda' ? 'GPU' : "CPU (slow: the GPU couldn't be used)";
    if (engine.device !== 'cuda') where.className = 'warn';
    text.append(`${engine.model} on `, where);
    ui.engine.append(text);
  }
  renderPickers();
  if (document.activeElement !== ui.vocabText) {
    ui.vocabText.value = engine.settings.vocabulary ?? '';
    ui.vocabSave.disabled = true;
  }
  ui.tidyToggle.checked = engine.settings.tidy_speech !== 'off';
  ui.folderButton.title = `Open ${homePath(engine.folder ?? '')}`;
  if (!recordingOrPaused()) setLevels([]);
}

/** Where the shown meeting's file is, with export and delete. */
export function renderFile(): void {
  const session = store.shown;
  ui.fileSection.hidden = !session;
  if (!session) return;
  for (const link of ui.fileSection.querySelectorAll<HTMLAnchorElement>(
    'a[data-export]',
  )) {
    link.href = `/api/meetings/${session.id}/export.${link.dataset.export}`;
  }
  ui.filePath.textContent = session.path
    ? homePath(session.path)
    : `Saved to ${homePath(store.engine?.folder ?? '')} once the first words are transcribed.`;
  const isRecording = session.id === store.live?.id && recordingOrPaused();
  ui.archiveButton.textContent = session.archived
    ? 'Unarchive meeting'
    : 'Archive meeting';
  ui.archiveButton.disabled = isRecording && !session.archived;
  ui.archiveButton.title = ui.archiveButton.disabled
    ? 'Stop recording before archiving this meeting.'
    : session.archived
      ? 'Put it back in the list of meetings.'
      : 'Keep it, but take it out of the list of meetings.';
  ui.deleteButton.disabled = isRecording;
  ui.deleteButton.title = isRecording
    ? 'Stop recording before deleting this meeting.'
    : '';
  if (isRecording) hideDeleteConfirm();
}

/** Fetch the export ourselves (rather than following a link) so we know when it's done. */
async function download(session: Session, kind: 'txt' | 'md'): Promise<void> {
  const response = await fetch(`/api/meetings/${session.id}/export.${kind}`);
  if (!response.ok)
    throw new Error(
      `Couldn't download the transcript (error ${response.status}).`,
    );
  const blob = await response.blob();
  const match = /filename\*=UTF-8''([^;]+)/i.exec(
    response.headers.get('Content-Disposition') ?? '',
  );
  const name = match?.[1] ? decodeURIComponent(match[1]) : `transcript.${kind}`;
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = name;
  document.body.append(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 30_000);
  toast(`Downloaded “${name}”`);
}

// Deleting asks once more in place, rather than in a browser dialog.
function hideDeleteConfirm(): void {
  ui.deleteConfirm.hidden = true;
  ui.deleteButton.hidden = false;
}

export function initPanel(): void {
  ui.fileSection.addEventListener('click', (event) => {
    const item = (event.target as Element).closest<HTMLElement>(
      '[data-export]',
    );
    const session = store.shown;
    if (!item || !session) return;
    const kind = item.dataset.export;
    if (kind === 'copy') {
      event.preventDefault();
      void copyTranscript();
    } else if (kind === 'reveal') {
      event.preventDefault();
      void act(null, () => api(`/api/meetings/${session.id}/reveal`, {}));
    } else if (kind === 'txt' || kind === 'md') {
      event.preventDefault();
      void act(item, () => download(session, kind));
    }
  });

  ui.folderButton.addEventListener(
    'click',
    () => void act(null, () => api('/api/folder/open', {})),
  );

  ui.archiveButton.addEventListener('click', () => {
    const session = store.shown;
    if (session)
      void act(ui.archiveButton, () =>
        archiveMeeting(session.id, !session.archived),
      );
  });

  ui.deleteButton.addEventListener('click', () => {
    ui.deleteButton.hidden = true;
    ui.deleteConfirm.hidden = false;
    ui.deleteCancel.focus();
  });
  ui.deleteCancel.addEventListener('click', () => {
    hideDeleteConfirm();
    ui.deleteButton.focus();
  });
  ui.deleteYes.addEventListener(
    'click',
    () =>
      void act(ui.deleteYes, async () => {
        const session = store.shown;
        if (!session) return;
        await api(`/api/meetings/${session.id}/delete`, {});
        hideDeleteConfirm();
        forgetMeeting(session.id);
        toast('Moved to the Trash.');
      }),
  );

  ui.vocabText.addEventListener('input', () => {
    ui.vocabSave.disabled =
      ui.vocabText.value.trim() === (store.engine?.settings.vocabulary ?? '');
  });
  ui.tidyToggle.addEventListener('change', () => {
    const on = ui.tidyToggle.checked;
    void act(ui.tidyToggle, async () => {
      try {
        await api('/api/tidy', { on });
      } catch (error) {
        ui.tidyToggle.checked = !on;
        throw error;
      }
      if (store.engine) store.engine.settings.tidy_speech = on ? 'on' : 'off';
      toast(
        on
          ? 'Ums and uhs will be left out.'
          : 'Speech will be kept word for word.',
      );
    });
  });

  ui.vocabForm.addEventListener('submit', (event) => {
    event.preventDefault();
    void act(null, async () => {
      await api('/api/vocabulary', { text: ui.vocabText.value });
      if (store.engine)
        store.engine.settings.vocabulary = ui.vocabText.value.trim();
      ui.vocabSave.disabled = true;
      toast('Names and terms saved.');
    });
  });
}
