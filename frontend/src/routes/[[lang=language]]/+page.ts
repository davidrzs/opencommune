import { redirect } from '@sveltejs/kit';
export function load({ url }) {
  // The site has no language-neutral pages: the root is the German start page.
  if (url.pathname === '/') redirect(307, '/de');
}
