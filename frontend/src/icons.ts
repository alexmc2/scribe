// Line icons, drawn on a 20 × 20 grid in the current text colour.

const PATHS = {
  microphone:
    '<rect x="7" y="2.5" width="6" height="10" rx="3"/><path d="M4.5 9.5a5.5 5.5 0 0 0 11 0M10 15v2.5"/>',
  speaker:
    '<path d="M3.5 7.5h3l4-3.5v12l-4-3.5h-3z"/><path d="M13.5 7.2a4 4 0 0 1 0 5.6M15.6 5a7 7 0 0 1 0 10"/>',
  display:
    '<rect x="2.5" y="3.5" width="15" height="10" rx="1.5"/><path d="M7 17h6M10 13.5V17"/>',
  headset:
    '<path d="M3.5 12.5V10a6.5 6.5 0 0 1 13 0v2.5"/><rect x="2.5" y="11.5" width="3.5" height="5.5" rx="1.2"/><rect x="14" y="11.5" width="3.5" height="5.5" rx="1.2"/>',
  off: '<circle cx="10" cy="10" r="6.5"/><path d="M5.4 14.6l9.2-9.2"/>',
  check: '<path d="M4.5 10.5l3.5 3.5 7.5-8"/>',
  chevron: '<path d="M6 8l4 4 4-4"/>',
  alert: '<circle cx="10" cy="10" r="7"/><path d="M10 6.5v4.5M10 13.6v.1"/>',
  copy: '<rect x="7" y="7" width="10" height="10" rx="2"/><path d="M13 4.5A1.5 1.5 0 0 0 11.5 3h-7A1.5 1.5 0 0 0 3 4.5v7A1.5 1.5 0 0 0 4.5 13"/>',
  archive:
    '<rect x="2.5" y="3.5" width="15" height="4" rx="1"/><path d="M4 7.5v8a1 1 0 0 0 1 1h10a1 1 0 0 0 1-1v-8M8 11h4"/>',
  unarchive:
    '<rect x="2.5" y="3.5" width="15" height="4" rx="1"/><path d="M4 7.5v8a1 1 0 0 0 1 1h10a1 1 0 0 0 1-1v-8M10 14.5v-4.5M7.8 12.2L10 10l2.2 2.2"/>',
  back: '<path d="M12 5l-5 5 5 5"/>',
  name: '<circle cx="8" cy="6.5" r="3"/><path d="M2.5 16.5a5.5 5.5 0 0 1 11 0M15.5 6.5v5M13 9h5"/>',
} as const;

export type Icon = keyof typeof PATHS;

export function icon(
  name: Icon,
  className = 'icon',
  size = 20,
  strokeWidth = 1.6,
): string {
  return (
    `<svg class="${className}" viewBox="0 0 20 20" width="${size}" height="${size}" aria-hidden="true" fill="none" ` +
    `stroke="currentColor" stroke-width="${strokeWidth}" stroke-linecap="round" stroke-linejoin="round">${PATHS[name]}</svg>`
  );
}
