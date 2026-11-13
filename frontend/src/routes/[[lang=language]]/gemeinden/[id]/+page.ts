import { api } from '$lib/api';
import { documentQuery, readFilters } from '$lib/documents';
import type { CommuneDetail, DocumentPage } from '$lib/types';
import { error } from '@sveltejs/kit';
export async function load({ params, url, fetch }) {
  if (!/^\d+$/.test(params.id)) error(404, 'Commune not found');
  // the selectors' state is the URL query (documents.ts)
  const filters = readFilters(url);
  const query = String(documentQuery(filters, params.id));
  const [commune, results]: [CommuneDetail, DocumentPage] = await Promise.all([
    api(fetch, `/communes/${params.id}`),
    api(fetch, `/documents?${query}`)
  ]);
  return { commune, results, filters, query };
}
