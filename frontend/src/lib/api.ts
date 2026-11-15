import { error } from '@sveltejs/kit';
type Fetch = typeof fetch;
// The JSON API on the same origin. `fetch` is the one SvelteKit passes to a load function.
export async function api(fetch: Fetch, path: string) {
  let response: Response;
  try {
    response = await fetch(`/api${path}`, { signal: AbortSignal.timeout(15000) });
  } catch {
    error(503, 'archive unavailable'); // +error.svelte shows the localised text
  }
  if (!response.ok) error(response.status, 'archive request failed');
  return await response.json();
}
// A request whose refusals the page explains itself: the JSON, or null with the status when the
// API answers 400 (invalid parameters) or 503 (a part this server does not have). Other failures
// go to the error page, as with `api`.
export async function apiOrStatus<T>(
  fetch: Fetch,
  path: string
): Promise<{ status: number; data: T | null }> {
  let response: Response;
  try {
    response = await fetch(`/api${path}`, { signal: AbortSignal.timeout(15000) });
  } catch {
    error(503, 'archive unavailable');
  }
  if (response.ok) return { status: response.status, data: await response.json() };
  if (response.status === 400 || response.status === 503)
    return { status: response.status, data: null };
  error(response.status, 'archive request failed');
}
// Data a page can do without: null when the request fails.
export async function apiOptional(fetch: Fetch, path: string) {
  try {
    const response = await fetch(`/api${path}`, { signal: AbortSignal.timeout(15000) });
    return response.ok ? await response.json() : null;
  } catch {
    return null;
  }
}
