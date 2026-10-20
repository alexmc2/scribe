// A dropdown for choosing an input device: a button that opens a listbox.
// Keyboard: arrows/Home/End move, Enter or Space chooses, Escape closes.

import { child } from './dom.js';
import { icon } from './icons.js';
import type { Icon } from './icons.js';
import type { InputOption } from './types.js';

const open = new Set<Picker>();

export class Picker {
  readonly root: HTMLElement;
  options: InputOption[] = [];
  private value: string | null = null;
  private shown: InputOption[] = []; // options plus a "not connected" entry if needed
  private active = -1;
  private readonly role: string;
  private readonly button: HTMLButtonElement;
  private readonly list: HTMLElement;

  constructor(
    root: HTMLElement,
    private readonly onChoose: (value: string) => void,
    private readonly onOpen: () => void = () => {},
  ) {
    this.root = root;
    this.role = root.dataset.role ?? 'microphone'; // "microphone" or "computer"
    const labelId = root.dataset.labelledBy ?? '';
    root.innerHTML = `
      <button type="button" class="picker-button" aria-haspopup="listbox" aria-expanded="false"
              aria-labelledby="${labelId} ${root.id}-value">
        <span class="picker-icon"></span>
        <span class="picker-text">
          <span class="picker-role" aria-hidden="true"></span>
          <span class="picker-value" id="${root.id}-value"></span>
        </span>
        ${icon('chevron', 'chevron')}
      </button>
      <ul class="picker-list" role="listbox" tabindex="-1" aria-labelledby="${labelId}"></ul>`;
    this.button = child<HTMLButtonElement>(root, '.picker-button');
    this.list = child(root, '.picker-list');
    child(this.button, '.picker-role').textContent =
      document.getElementById(labelId)?.textContent ?? '';

    this.button.addEventListener('click', () =>
      this.isOpen ? this.close() : this.open(),
    );
    this.button.addEventListener('keydown', (event) => {
      if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
        event.preventDefault();
        this.open();
      }
    });
    this.list.addEventListener('keydown', (event) => this.onKey(event));
    this.list.addEventListener('click', (event) => {
      const item = (event.target as Element).closest<HTMLElement>(
        '[role=option]',
      );
      if (item) this.choose(Number(item.dataset.index));
    });
    this.list.addEventListener('mousemove', (event) => {
      const item = (event.target as Element).closest<HTMLElement>(
        '[role=option]',
      );
      if (item) this.highlight(Number(item.dataset.index));
    });
  }

  get isOpen(): boolean {
    return this.list.classList.contains('open');
  }

  setOptions(options: InputOption[]): void {
    this.options = options;
    this.render();
  }

  setValue(value: string): void {
    this.value = value;
    this.render();
  }

  open(): void {
    for (const other of open) if (other !== this) other.close();
    open.add(this);
    this.onOpen();
    this.list.classList.add('open');
    this.button.setAttribute('aria-expanded', 'true');
    this.highlight(
      Math.max(
        0,
        this.shown.findIndex((o) => o.value === this.value),
      ),
    );
    this.list.focus();
  }

  close(returnFocus = false): void {
    if (!this.isOpen) return;
    open.delete(this);
    this.list.classList.remove('open');
    this.button.setAttribute('aria-expanded', 'false');
    if (returnFocus) this.button.focus();
  }

  private iconFor(option: InputOption): Icon {
    if (option.icon === 'default')
      return this.role === 'microphone' ? 'microphone' : 'speaker';
    return option.icon;
  }

  private render(): void {
    let options = this.options;
    if (
      this.value &&
      options.length &&
      !options.some((o) => o.value === this.value)
    ) {
      // A device that was chosen before but isn't plugged in now.
      const name = this.value.split('.').pop() ?? this.value;
      options = [
        ...options,
        {
          value: this.value,
          label: name,
          detail: 'Not connected',
          icon: 'off',
        },
      ];
    }
    this.shown = options;

    const selected = options.find((o) => o.value === this.value);
    child(this.button, '.picker-icon').innerHTML = selected
      ? icon(this.iconFor(selected))
      : '';
    const value = child(this.button, '.picker-value');
    value.textContent = selected?.label ?? 'Loading…';
    value.classList.toggle('warning', Boolean(selected?.warning));
    this.button.title = selected?.detail
      ? `${selected.label}: ${selected.detail}`
      : '';
    this.button.classList.toggle('is-off', selected?.value === 'off');

    this.list.replaceChildren();
    options.forEach((option, index) => {
      if (option.value === 'off' && index > 0) {
        const rule = document.createElement('li');
        rule.className = 'option-rule';
        rule.setAttribute('role', 'separator');
        this.list.append(rule);
      }
      this.list.append(this.optionItem(option, index));
    });
  }

  private optionItem(option: InputOption, index: number): HTMLElement {
    const item = document.createElement('li');
    item.className = 'option';
    item.id = `${this.root.id}-option-${index}`;
    item.dataset.index = String(index);
    item.setAttribute('role', 'option');
    item.setAttribute('aria-selected', String(option.value === this.value));
    item.innerHTML = `${icon(this.iconFor(option))}
      <span class="option-text"><span class="option-label"></span><span class="option-detail"></span></span>
      ${icon('check', 'option-check')}`;
    child(item, '.option-label').textContent = option.label;
    const detail = child(item, '.option-detail');
    detail.textContent = option.detail ?? '';
    detail.classList.toggle('warning', Boolean(option.warning));
    return item;
  }

  private highlight(index: number): void {
    this.active = index;
    for (const item of this.list.querySelectorAll<HTMLElement>(
      '[role=option]',
    )) {
      item.classList.toggle('active', Number(item.dataset.index) === index);
    }
    const item = this.list.querySelector(`[data-index="${index}"]`);
    if (item) {
      this.list.setAttribute('aria-activedescendant', item.id);
      item.scrollIntoView({ block: 'nearest' });
    }
  }

  private onKey(event: KeyboardEvent): void {
    const last = this.shown.length - 1;
    const moves: Record<string, number> = {
      ArrowDown: this.active + 1,
      ArrowUp: this.active - 1,
      Home: 0,
      End: last,
    };
    const move = moves[event.key];
    if (move !== undefined) {
      event.preventDefault();
      this.highlight(Math.min(last, Math.max(0, move)));
    } else if (event.key === 'Enter' || event.key === ' ') {
      event.preventDefault();
      this.choose(this.active);
    } else if (event.key === 'Escape') {
      event.preventDefault();
      event.stopPropagation();
      this.close(true);
    } else if (event.key === 'Tab') {
      this.close();
    }
  }

  private choose(index: number): void {
    const option = this.shown[index];
    this.close(true);
    if (option && option.value !== this.value) {
      this.setValue(option.value);
      this.onChoose(option.value);
    }
  }
}
