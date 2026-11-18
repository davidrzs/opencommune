import { apiOptional } from '$lib/api';
import type { Commune } from '$lib/types';
// Rendered in the browser only; the server sends index.html for every page.
export const ssr = false;
export async function load({ fetch }) {
  // every commune for the map, the commune search and the start page's list; none when the API
  // cannot be reached, so that a page's own request decides between its content and the error page
  const communes: Commune[] = (await apiOptional(fetch, '/communes')) ?? [];
  return { communes: communes.sort((a, b) => a.name.localeCompare(b.name, 'de')) };
}
