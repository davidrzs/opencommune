import { apiOptional } from '$lib/api';
import type { DocumentPage } from '$lib/types';
import { redirect } from '@sveltejs/kit';
export function load({ fetch, url }) {
  // The site has no language-neutral pages: the root is the German start page.
  if (url.pathname === '/') redirect(307, '/de');
  // The number of files, each counted once: the communes' counts would count a file once per
  // commune that links it. Not awaited, so the map does not wait for it.
  const files: Promise<number | null> = apiOptional(fetch, '/documents?limit=0').then(
    (page: DocumentPage | null) => page?.total ?? null
  );
  return { files };
}
