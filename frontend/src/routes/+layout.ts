import { api } from '$lib/api';
import type { Commune } from '$lib/types';
// Rendered in the browser only; the server sends index.html for every page.
export const ssr = false;
export async function load({ fetch }) {
  // The slim list for the map and the commune search: name, canton, position, counts, access.
  const communes: Commune[] = await api(fetch, '/archive/communes');
  return { communes: communes.sort((a, b) => a.name.localeCompare(b.name, 'de')) };
}
