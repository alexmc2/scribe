// What to record: the Microphone and Computer audio pickers in the panel, and
// the "recording from" chips with level bars in the top bar.

import { api, errorMessage } from './api.js';
import { byId, child, ui } from './dom.js';
import { icon } from './icons.js';
import { Picker } from './picker.js';
import { renderSettings } from './panel.js';
import { store } from './state.js';
import { toast } from './toast.js';
import type { InputChoices, Snapshot } from './types.js';

let micPicker: Picker;
let computerPicker: Picker;

export function pickers(): Picker[] {
  return [micPicker, computerPicker];
}

export async function loadInputs(): Promise<void> {
  if (!store.engine) return;
  try {
    const choices = await api<InputChoices>('/api/inputs');
    micPicker.setOptions(choices.microphone);
    computerPicker.setOptions(choices.computer_audio);
  } catch {
    // Shown by the connection banner.
  }
}

export function inputsLoaded(): boolean {
  return micPicker.options.length > 0;
}

/** Show the saved choices in the pickers. */
export function renderPickers(): void {
  if (!store.engine) return;
  micPicker.setValue(store.engine.settings.microphone);
  computerPicker.setValue(store.engine.settings.computer_audio);
}

async function changeInput(
  setting: 'microphone' | 'computer_audio',
  value: string,
): Promise<void> {
  // Send only the setting that changed, so the other can't be overwritten by a stale value.
  try {
    const snapshot = await api<Snapshot>('/api/inputs', { [setting]: value });
    if (store.engine) {
      store.engine.settings = snapshot.settings;
      store.engine.inputs = snapshot.inputs;
    }
    void loadInputs();
  } catch (error) {
    toast(errorMessage(error), true);
  }
  renderSettings();
  renderListening();
}

/** The top bar's "recording from" chips: one per input, with a live level. */
export function renderListening(): void {
  const inputs = store.engine?.state === 'recording' ? store.engine.inputs : [];
  ui.listening.hidden = !inputs.length;
  const key = JSON.stringify(inputs);
  if (ui.listening.dataset.key === key) return; // unchanged; keep the bars as they are
  ui.listening.dataset.key = key;
  ui.listening.replaceChildren(
    ...inputs.map((input) => {
      const chip = document.createElement('span');
      chip.className = 'source';
      chip.title = `Recording from ${input.label}${input.detail ? ` (${input.detail})` : ''}`;
      chip.innerHTML = `${icon(input.icon === 'default' ? 'microphone' : input.icon)}<span class="source-name"></span>
        <span class="bars" aria-hidden="true"><i></i><i></i><i></i><i></i><i></i></span>`;
      child(chip, '.source-name').textContent = input.label;
      return chip;
    }),
  );
}

const BAR_STEPS = [0.12, 0.28, 0.42, 0.56, 0.7]; // level (0–1) needed to light each bar

export function setLevels(levels: number[]): void {
  ui.listening.querySelectorAll('.source').forEach((chip, i) => {
    const level = levels[i] ?? 0;
    chip
      .querySelectorAll('.bars i')
      .forEach((bar, n) =>
        bar.classList.toggle('on', level >= (BAR_STEPS[n] ?? 1)),
      );
  });
}

export function initInputs(): void {
  micPicker = new Picker(
    byId('micPicker'),
    (value) => void changeInput('microphone', value),
    () => void loadInputs(),
  );
  computerPicker = new Picker(
    byId('computerPicker'),
    (value) => void changeInput('computer_audio', value),
    () => void loadInputs(), // devices come and go; refresh while open
  );
  window.addEventListener('focus', () => void loadInputs());
}
