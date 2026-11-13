import { api, apiOptional } from '$lib/api';
import type { CommuneDetail } from '$lib/types';
import { error } from '@sveltejs/kit';
const TABS = ['documents', 'decisions', 'votes', 'finance'] as const;
export async function load({ params, url, fetch }) {
  if (!/^\d+$/.test(params.id)) error(404, 'Commune not found');
  // votes and finances come from the dataset, served only where it is configured
  const [commune, dataset]: [CommuneDetail, any] = await Promise.all([
    api(fetch, `/archive/communes/${params.id}`),
    apiOptional(fetch, `/dataset/communes/${params.id}`)
  ]);
  const asked = url.searchParams.get('tab') as (typeof TABS)[number] | null;
  const q = url.searchParams.get('q') || '';
  const year = /^\d{4}$/.test(url.searchParams.get('year') || '')
    ? url.searchParams.get('year')!
    : '';
  const offset = Math.max(0, Number(url.searchParams.get('offset')) || 0);
  // without a tab asked for, the first one with content: published documents, then the dataset
  // a dataset tab only when the dataset has rows for it (an old link may ask for it anyway)
  const available = (t: (typeof TABS)[number]) =>
    t === 'votes' ? !!dataset?.votes?.length : t === 'finance' ? !!dataset?.finance?.length : true;
  const tab =
    asked && TABS.includes(asked) && available(asked)
      ? asked
      : commune.documents > 0
        ? 'documents'
        : dataset?.votes?.length
          ? 'votes'
          : dataset?.finance?.length
            ? 'finance'
            : 'documents';
  let results = null;
  if (tab === 'documents' || tab === 'decisions') {
    const filters = new URLSearchParams({ commune: params.id, q, offset: String(offset) });
    if (year && tab === 'documents') filters.set('year', year);
    results = await api(
      fetch,
      `${tab === 'decisions' ? '/decisions' : '/archive/documents'}?${filters}`
    );
  }
  return { commune, tab, q, year, offset, results, dataset };
}
