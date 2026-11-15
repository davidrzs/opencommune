import { api, apiOrStatus } from '$lib/api';
import { PAGE_SIZE, documentQuery, readFilters, textQuery } from '$lib/documents';
import type { DocumentPage, TextPage } from '$lib/types';
export async function load({ url, fetch }) {
  // the selectors' state is the URL query (documents.ts)
  const filters = readFilters(url);
  // With words in the box, the text of the pages is searched. 400: the server refused the words.
  // 503: this server has no full-text index, and the titles are searched instead.
  let notice: 'invalid' | 'unavailable' | null = null;
  if (filters.q) {
    const query = String(textQuery(filters));
    const { status, data } = await apiOrStatus<TextPage>(fetch, `/pages?${query}`);
    if (data) return { results: data, filters, query, endpoint: '/api/pages', notice };
    if (status === 400) {
      const results: TextPage = {
        total: 0,
        capped: false,
        offset: filters.offset,
        limit: PAGE_SIZE,
        facets: { years: [], sections: [], cantons: [], communes: [] },
        items: []
      };
      return { results, filters, query, endpoint: '/api/pages', notice: 'invalid' as const };
    }
    notice = 'unavailable';
  }
  // without words, or without the index: the commune page's list across every commune, which has
  // no canton filter
  filters.canton = '';
  const query = String(documentQuery(filters));
  const results: DocumentPage = await api(fetch, `/documents?${query}`);
  return { results, filters, query, endpoint: '/api/documents', notice };
}
