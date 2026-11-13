import { api } from '$lib/api';
import { documentQuery, readFilters } from '$lib/documents';
import type { DocumentPage } from '$lib/types';
export async function load({ url, fetch }) {
  // the commune page's list across every commune; the selectors' state is the URL query
  const filters = readFilters(url);
  const query = String(documentQuery(filters));
  const results: DocumentPage = await api(fetch, `/documents?${query}`);
  return { results, filters, query };
}
