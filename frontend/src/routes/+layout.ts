import { api } from '$lib/api';
import type { Commune } from '$lib/types';
// Rendered in the browser only; the server sends index.html for every page.
export const ssr = false;
export async function load({ fetch }) {
  // every commune for the map, the commune search and the start page's list
  const communes: Commune[] = await api(fetch, '/communes');
  return { communes: communes.sort((a, b) => a.name.localeCompare(b.name, 'de')) };
}
