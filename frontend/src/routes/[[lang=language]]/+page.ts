import { apiOptional } from '$lib/api';
import { redirect } from '@sveltejs/kit';
export async function load({ fetch, url }) {
  // The site has no language-neutral pages: the root is the German start page.
  if (url.pathname === '/') redirect(307, '/de');
  const [findings, coverage] = await Promise.all([
    apiOptional(fetch, '/dataset/findings'),
    apiOptional(fetch, '/dataset/coverage')
  ]);
  return { findings, coverage };
}
