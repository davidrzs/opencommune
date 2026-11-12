import adapter from '@sveltejs/adapter-static';
// A single-page app: the Rust server (server/) answers every page path with index.html.
export default { kit: { adapter: adapter({ fallback: 'index.html' }) } };
