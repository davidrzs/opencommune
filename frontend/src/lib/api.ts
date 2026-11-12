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
// Data that only some installations have (the dataset): null when the API lacks it.
export async function apiOptional(fetch: Fetch, path: string) {
  try {
    const response = await fetch(`/api${path}`, { signal: AbortSignal.timeout(15000) });
    return response.ok ? await response.json() : null;
  } catch {
    return null;
  }
}
