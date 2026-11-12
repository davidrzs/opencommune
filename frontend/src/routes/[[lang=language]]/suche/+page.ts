import { api } from '$lib/api';
export async function load({ url, fetch }) {
  const q = url.searchParams.get('q') || '';
  const offset = Math.max(0, Number(url.searchParams.get('offset')) || 0);
  return {
    q,
    offset,
    results: await api(fetch, `/decisions?${new URLSearchParams({ q, offset: String(offset) })}`)
  };
}
