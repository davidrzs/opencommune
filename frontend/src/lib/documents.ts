// The document list's state, kept in the page's URL query so that a filtered view can be linked.
export const PAGE_SIZE = 20;
// the selectors, the family (set from the commune page's holdings table) and the text field, by
// their /api/documents parameter
export const FILTERS = ['section', 'family', 'body', 'year', 'q'] as const;
export type Filters = Record<(typeof FILTERS)[number], string> & { offset: number };

export function readFilters(url: URL): Filters {
  const get = (key: string) => url.searchParams.get(key)?.trim() || '';
  const year = get('year');
  return {
    section: get('section'),
    family: get('family'),
    body: get('body'),
    year: /^\d{4}$/.test(year) ? year : '',
    q: get('q'),
    offset: Math.max(0, Math.floor(Number(url.searchParams.get('offset')) || 0))
  };
}

// The /api/documents query for these filters: empty ones left out, one page of PAGE_SIZE.
export function documentQuery(filters: Filters, commune?: string) {
  const query = new URLSearchParams();
  if (commune) query.set('commune', commune);
  for (const key of FILTERS) if (filters[key]) query.set(key, filters[key]);
  query.set('offset', String(filters.offset));
  query.set('limit', String(PAGE_SIZE));
  return query;
}

export const filtered = (filters: Filters) => FILTERS.some((key) => filters[key]);

// The original through this site at a commune's address, opened at a page when one is given.
export function originalLink(url: string | null, commune?: number, page?: number) {
  if (!url) return '';
  const query = new URLSearchParams();
  if (commune !== undefined) query.set('commune', String(commune));
  if (page !== undefined) query.set('page', String(page));
  const search = String(query);
  return search ? `${url}${url.includes('?') ? '&' : '?'}${search}` : url;
}
