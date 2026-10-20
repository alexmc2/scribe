// The shapes of the data the Python server sends (see scribe/server.py and
// scribe/engine.py). Field names follow the server's snake_case.

export type RecorderState = "loading" | "ready" | "recording" | "paused" | "error";

export interface Block {
  id: number;
  start: number; // seconds since the meeting started
  end: number;
  text: string;
  speaker: string | null;
  closed: boolean;
}

export interface Session {
  id: string;
  title: string;
  started_at: string; // ISO 8601
  ended_at: string | null;
  model: string;
  inputs: string[];
  txt_name: string;
  blocks: Block[];
  live: boolean;
  elapsed: number;
  path: string; // the readable .txt file, empty until something is saved
}

/** One row in the sidebar's list of meetings. */
export interface MeetingSummary {
  id: string;
  title: string;
  started_at: string;
  ended_at: string | null;
  duration: number;
  words: number;
  txt_name: string;
  preview: string; // the first words, for untitled meetings
}

export interface Settings {
  microphone: string; // "default", "off", or a device name
  computer_audio: string;
  vocabulary: string;
}

export type IconName = "microphone" | "speaker" | "display" | "headset" | "off" | "default";

/** An input being recorded right now, shown as a chip in the top bar. */
export interface ActiveInput {
  label: string;
  detail: string;
  icon: IconName;
  role: "microphone" | "computer";
}

/** One choice in the Microphone or Computer audio picker. */
export interface InputOption {
  value: string;
  label: string;
  detail?: string;
  icon: IconName;
  warning?: boolean;
}

export interface InputChoices {
  microphone: InputOption[];
  computer_audio: InputOption[];
}

/** The recorder's state, sent whole on connect and after recording actions. */
export interface Snapshot {
  state: RecorderState;
  message: string;
  input_error: string | null;
  inputs: ActiveInput[];
  model: string;
  device: string;
  session: Session | null;
  preview: string;
  settings: Settings;
  folder: string;
  last_saved: string | null;
  save_error: string | null;
}

/** Live events from /api/events, by name. */
export interface ServerEvents {
  snapshot: Snapshot;
  state: Pick<Snapshot, "state" | "message" | "input_error" | "inputs" | "model" | "device" | "settings">;
  session: { session: Session };
  block: { session_id: string; block: Block };
  preview: { session_id: string; text: string };
  saved: { session_id: string; at: string; path: string };
  save_failed: { session_id: string; message: string };
  levels: { levels: number[] };
  meetings_changed: Record<string, never>;
  deleted: { session_id: string };
}
