import { api, apiOptional } from '$lib/api';
import { documentQuery, readFilters } from '$lib/documents';
import type { CommuneDetail, DocumentPage, Facet } from '$lib/types';
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
  // A server without pages per family: the chart shows the documents per year, the year facet of
  // the commune's list without filters (a facet leaves out only its own filter).
  let years: Facet[] | null = null;
  if (commune.holdings.length && commune.holdings.some((h) => h.pages === undefined)) {
    const plain =
      !filters.q && !filters.section && !filters.family && !filters.first_family && !filters.body;
    const unfiltered: DocumentPage | null = plain
      ? results
      : await apiOptional(fetch, `/documents?commune=${params.id}&limit=0`);
    years = unfiltered?.facets.years ?? null;
  }
  return { commune, results, filters, query, years };
}
