import { api } from '$lib/api';
import type { Decision } from '$lib/types';
export async function load({ params, fetch }) {
  const decision: Decision = await api(fetch, `/decisions/${encodeURIComponent(params.id)}`);
  return { decision };
}
