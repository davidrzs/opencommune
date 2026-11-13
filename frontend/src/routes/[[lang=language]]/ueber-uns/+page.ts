import { apiOptional } from '$lib/api';
import type { Run } from '$lib/types';
export async function load({ fetch }) {
  // the classification runs and what their settings mean for the data; the page stands without them
  const runs: Run[] | null = await apiOptional(fetch, '/runs');
  return { runs };
}
