// Redraws everything that depends on the recorder's state.

import {
  renderBanner,
  renderControls,
  renderHeader,
  renderStatus,
} from './header.js';
import { renderListening } from './inputs.js';
import { renderSettings } from './panel.js';
import { renderEmpty, renderPreview } from './transcript.js';

export function renderAll(): void {
  renderStatus();
  renderControls();
  renderHeader();
  renderBanner();
  renderSettings();
  renderEmpty();
  renderPreview();
  renderListening();
}
