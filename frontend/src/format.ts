// Dates, durations and text, formatted for display.

import type { Session } from './types.js';

const pad = (n: number): string => String(n).padStart(2, '0');

export const clockFormat = new Intl.DateTimeFormat(undefined, {
  hour: '2-digit',
  minute: '2-digit',
});
export const secondsFormat = new Intl.DateTimeFormat(undefined, {
  hour: '2-digit',
  minute: '2-digit',
  second: '2-digit',
});
const dayFormat = new Intl.DateTimeFormat(undefined, {
  weekday: 'long',
  day: 'numeric',
  month: 'long',
});
export const fullDayFormat = new Intl.DateTimeFormat(undefined, {
  weekday: 'long',
  day: 'numeric',
  month: 'long',
  year: 'numeric',
});

/** Seconds into a meeting as "12:31" or "1:02:10". */
export function offset(seconds: number): string {
  const s = Math.max(0, Math.floor(seconds));
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  return h ? `${h}:${pad(m)}:${pad(s % 60)}` : `${m}:${pad(s % 60)}`;
}

export function duration(seconds: number): string {
  const minutes = Math.round(seconds / 60);
  if (minutes < 1) return 'under a minute';
  if (minutes < 60) return `${minutes} min`;
  return `${Math.floor(minutes / 60)} h ${minutes % 60} min`;
}

/** "Today", "Yesterday", or the date, for grouping meetings. */
export function dayLabel(date: Date): string {
  const today = new Date();
  const yesterday = new Date(today);
  yesterday.setDate(today.getDate() - 1);
  if (date.toDateString() === today.toDateString()) return 'Today';
  if (date.toDateString() === yesterday.toDateString()) return 'Yesterday';
  return date.getFullYear() === today.getFullYear()
    ? dayFormat.format(date)
    : fullDayFormat.format(date);
}

export function elapsedOf(session: Session): number {
  const end = session.ended_at ? new Date(session.ended_at) : new Date();
  return (end.getTime() - new Date(session.started_at).getTime()) / 1000;
}

export function wordCount(session: Session): number {
  return session.blocks.reduce(
    (n, b) => n + (b.text ? b.text.split(/\s+/).length : 0),
    0,
  );
}

/** Paragraphs as plain text for copying, separated by blank lines. Each says
 * who spoke only when more than one person did, so dictated text pastes clean. */
export function plainText(
  paragraphs: { speaker: string; text: string }[],
): string {
  const spoken = paragraphs.filter((p) => p.text);
  const named = new Set(spoken.map((p) => p.speaker)).size > 1;
  return spoken
    .map((p) => (named && p.speaker ? `${p.speaker}: ${p.text}` : p.text))
    .join('\n\n');
}

/** Text typed into the page, with runs of spaces and line breaks made single spaces. */
export const tidy = (text: string | null): string =>
  (text ?? '').replace(/\s+/g, ' ').trim();

/** "/home/someone/Documents" as "~/Documents". */
export const homePath = (path: string): string =>
  path.replace(/^\/home\/[^/]+/, '~');
