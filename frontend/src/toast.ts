// Short confirmations and error messages at the bottom of the window.

import { errorMessage } from "./api.js";
import { child, ui } from "./dom.js";
import { icon } from "./icons.js";

let timer = 0;

export function toast(message: string, isError = false): void {
  ui.toast.innerHTML = `${icon(isError ? "alert" : "check", "", 16, 1.8)}<span></span>`;
  child(ui.toast, "span").textContent = message;
  ui.toast.classList.toggle("error", isError);
  // Restart the entrance animation when one toast replaces another.
  ui.toast.hidden = true;
  void ui.toast.offsetWidth;
  ui.toast.hidden = false;
  clearTimeout(timer);
  timer = window.setTimeout(() => (ui.toast.hidden = true), isError ? 6000 : 3000);
}

/** Run an action for a button: disable it meanwhile, and show any error. */
export async function act(button: HTMLElement | null, action: () => Promise<unknown>): Promise<void> {
  const control = button as HTMLButtonElement | null;
  if (control) control.disabled = true;
  try {
    await action();
  } catch (error) {
    toast(errorMessage(error), true);
  } finally {
    if (control) control.disabled = false;
  }
}
