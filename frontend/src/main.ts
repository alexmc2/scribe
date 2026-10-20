// Entry point: wire up each part of the page, draw it, then start listening
// for live updates. Modules only define things; everything starts here.

import { initEditing } from "./editing.js";
import { initHeader, renderStatus } from "./header.js";
import { initInputs } from "./inputs.js";
import { initLayout } from "./layout.js";
import { connect } from "./live.js";
import { initMeetings } from "./meetings.js";
import { initPanel } from "./panel.js";
import { renderAll } from "./render.js";
import { store } from "./state.js";
import { initTranscript } from "./transcript.js";

initInputs();
initLayout();
initHeader();
initTranscript();
initEditing();
initMeetings();
initPanel();

// The recording clock in the top bar.
setInterval(() => {
  if (store.engine) renderStatus();
}, 1000);

store.connected = true; // until the first connection attempt says otherwise
renderAll();
connect();
