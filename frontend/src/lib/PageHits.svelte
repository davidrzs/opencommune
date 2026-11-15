<script lang="ts">
  import { originalLink } from './documents';
  import { copy, fmt, label, type Lang } from './i18n';
  import type { PageHit, Section } from './types';
  // A document's best pages in a full-text search: the page with a link to the original there, the
  // types of the sections that hold it, and the snippet with the matched words marked. `matching`:
  // how many of its pages match. `at`: the commune whose link to the original is used.
  let {
    hits,
    matching,
    sections,
    languages,
    lang,
    at
  }: {
    hits: PageHit[];
    matching: number;
    sections: Section[];
    languages: string[];
    lang: Lang;
    at?: number;
  } = $props();
  let t = $derived(copy[lang]);

  // The snippet as runs of plain and marked text. Offsets count code points, so the text is split
  // with Array.from. Svelte writes each run as text: nothing in a snippet is read as HTML.
  function runs(snippet: string, highlights: [number, number][]) {
    const chars = Array.from(snippet);
    const parts: { text: string; marked: boolean }[] = [];
    let at = 0;
    for (const [start, end] of [...highlights].sort((a, b) => a[0] - b[0])) {
      const from = Math.max(start, at);
      const to = Math.min(end, chars.length);
      if (to <= from) continue;
      if (from > at) parts.push({ text: chars.slice(at, from).join(''), marked: false });
      parts.push({ text: chars.slice(from, to).join(''), marked: true });
      at = to;
    }
    if (at < chars.length) parts.push({ text: chars.slice(at).join(''), marked: false });
    return parts;
  }
  const types = (hit: PageHit) =>
    [...new Set(hit.section_types)].map((type) => label(lang, 'section', type)).join(', ');
  // the colour of the first section that holds the page
  const family = (hit: PageHit) =>
    sections.find(
      (s) => s.type === hit.section_types[0] && s.first_page <= hit.page && hit.page <= s.last_page
    )?.family ?? 'other';
  // the snippet's language, when the document has one
  let textLang = $derived(
    languages.length === 1 && languages[0] !== 'other' ? languages[0] : undefined
  );
</script>

<div class="hits">
  <p class="hits-count">
    {matching === 1 ? t.matchingPageOne : t.matchingPages.replace('{n}', fmt(matching, lang))}
  </p>
  <ol>
    {#each hits as hit (hit.page)}<li class="hit family-{family(hit)}">
        <p class="hit-meta">
          <a
            href={originalLink(hit.original_url, at)}
            target="_blank"
            rel="noreferrer"
            title={t.openAt.replace('{n}', fmt(hit.page, lang))}
            >{t.pageAbbr} {fmt(hit.page, lang)} ↗</a
          >{hit.section_types.length ? ` · ${types(hit)}` : ''}
        </p>
        <p class="snippet" lang={textLang}>
          {#each runs(hit.snippet, hit.highlights) as run}{#if run.marked}<mark>{run.text}</mark
              >{:else}{run.text}{/if}{/each}
        </p>
      </li>{/each}
  </ol>
</div>

<style>
  .hits {
    margin: var(--space-md) 0 var(--space-lg);
  }
  .hits-count {
    font-size: var(--font-size-sm);
    color: var(--muted);
    margin-bottom: var(--space-xs);
  }
  ol {
    list-style: none;
    padding: 0;
    margin: 0;
    display: flex;
    flex-direction: column;
    gap: var(--space-sm);
  }
  .hit {
    background: var(--band);
    border-left: var(--marker-width) solid var(--family);
    padding: var(--space-sm) var(--space-md);
  }
  .hit-meta {
    font-size: var(--font-size-sm);
    color: var(--muted);
    margin-bottom: var(--space-2xs);
  }
  .hit-meta a {
    font-weight: var(--weight-semibold);
  }
  .snippet {
    font-size: var(--font-size-md);
    line-height: var(--line-height-normal);
    overflow-wrap: anywhere;
  }
  mark {
    background: var(--selection);
    color: var(--ink);
  }
</style>
