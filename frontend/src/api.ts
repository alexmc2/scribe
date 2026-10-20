// Talking to the Scribe server. POSTs are always JSON: the server refuses
// anything else, which keeps other websites from driving it.

export async function api<T = unknown>(path: string, body?: unknown): Promise<T> {
  const options: RequestInit =
    body === undefined
      ? {}
      : { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) };
  const response = await fetch(path, options);
  const data: unknown = await response.json().catch(() => ({}));
  if (!response.ok) {
    const message = (data as { error?: string }).error;
    throw new Error(message || `Scribe answered with an error (${response.status}).`);
  }
  return data as T;
}

export function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}
