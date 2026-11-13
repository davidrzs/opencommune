<script lang="ts">
  import { goto } from '$app/navigation';
  import { page } from '$app/state';
  import DocumentRow from './DocumentRow.svelte';
  import { FILTERS, PAGE_SIZE, filtered, type Filters } from './documents';
  import { copy, fmt, href, label, type Lang } from './i18n';
  import { BODY_KINDS, SECTION_TYPES, type DocumentPage, type Facet } from './types';
  // `commune`: the commune page's commune; without it the list spans every commune. `query`: the
  // /api/documents query the page loaded the list with.
  let {
    results,
    filters,
    query,
    lang,
    commune,
    empty
  }: {
    results: DocumentPage;
    filters: Filters;
    query: string;
    lang: Lang;
    commune?: number;
    empty?: string;
  } = $props();
  let t = $derived(copy[lang]);
  let form: HTMLFormElement;

  // One selector per facet. Values in the vocabulary's order, years newest first; a value without
  // a filter of its own (null: no year, no body, ...) is listed with its count but not selectable.
  type Key = 'section' | 'body' | 'year';
  let selectors = $derived([
    {
      key: 'section' as Key,
      name: t.sectionLabel,
      all: t.allSections,
      facet: results.facets.sections,
      order: SECTION_TYPES as readonly string[]
    },
    {
      key: 'body' as Key,
      name: t.bodyLabel,
      all: t.allBodies,
      facet: results.facets.bodies,
      order: BODY_KINDS as readonly string[]
    },
    {
      key: 'year' as Key,
      name: t.yearLabel,
      all: t.allYears,
      facet: results.facets.years,
      order: null
    }
  ]);
  function options(key: Key, facet: Facet[], order: readonly string[] | null) {
    const rank = (f: Facet) =>
      f.value === null
        ? Infinity
        : order
          ? order.indexOf(String(f.value)) + 1 || order.length + 1
          : -Number(f.value);
    const listed = [...facet].sort((a, b) => rank(a) - rank(b));
    // the chosen value stays visible when the other filters leave nothing of it
    if (filters[key] && !listed.some((f) => String(f.value) === filters[key]))
      listed.unshift({ value: filters[key], count: 0 });
    return listed;
  }
  const name = (key: Key, value: string | number | null) =>
    value === null ? t.noValue : key === 'year' ? String(value) : label(lang, key, value);

  // the filters go into the URL; the page's loader reads them from there
  function submit(event: SubmitEvent) {
    event.preventDefault();
    const data = new FormData(form);
    const query = new URLSearchParams();
    for (const key of FILTERS) {
      const value = String(data.get(key) ?? '').trim();
      if (value) query.set(key, value);
    }
    const search = String(query);
    goto(`${page.url.pathname}${search ? `?${search}` : ''}`, { keepFocus: true, noScroll: true });
  }
  // this page with one parameter changed or removed
  function link(key: string, value: string) {
    const query = new URLSearchParams(page.url.searchParams);
    if (key !== 'offset') query.delete('offset');
    if (value) query.set(key, value);
    else query.delete(key);
    const search = String(query);
    return search ? `?${search}` : page.url.pathname;
  }
</script>

<p class="small-note list-note">
  {t.classificationNote}
  <a href={`${href('/ueber-uns', lang)}#klassifikation`}>{t.classificationLink}</a>
</p>
<form class="document-filters" method="GET" bind:this={form} onsubmit={submit}>
  <div class="search-field">
    <input name="q" aria-label={t.docSearch} placeholder={t.docSearch} value={filters.q} /><button
      >{t.filter} ↗</button
    >
  </div>
  {#if filters.family}<p class="active-family family-{filters.family}">
      <input type="hidden" name="family" value={filters.family} /><i
        class="swatch"
        aria-hidden="true"
      ></i>{t.familyLabel}
      {label(lang, 'family', filters.family)}
      <a href={link('family', '')} aria-label={t.removeFilter} title={t.removeFilter}>×</a>
    </p>{/if}
  <div class="selectors">
    {#each selectors as s (s.key)}<select
        name={s.key}
        aria-label={s.name}
        value={filters[s.key]}
        onchange={() => form.requestSubmit()}
        ><option value="">{s.all}</option>{#each options(s.key, s.facet, s.order) as f}<option
            value={f.value === null ? '' : String(f.value)}
            disabled={f.value === null}>{name(s.key, f.value)} ({fmt(f.count, lang)})</option
          >{/each}</select
      >{/each}
  </div>
</form>
<div class="result-count">
  <span
    >{fmt(results.total, lang)}
    {results.total === 1 ? t.resultOne : t.result}</span
  >{#if filtered(filters)}<a href={page.url.pathname}>{t.reset}</a>{/if}
</div>
{#each results.items as doc (doc.sha256)}<DocumentRow
    {doc}
    {lang}
    {commune}
    section={filters.section}
    family={filters.family}
  />{:else}<div class="empty-state">
    <h2>{empty ?? t.noResults}</h2>
    {#if filters.year}<p>{t.unknownDate}</p>{/if}{#if filtered(filters)}<a href={page.url.pathname}
        >{t.reset}</a
      >{/if}
  </div>{/each}
<nav class="pagination" aria-label={t.result}>
  {#if filters.offset > 0}<a
      href={link('offset', filters.offset > PAGE_SIZE ? String(filters.offset - PAGE_SIZE) : '')}
      >← {t.prev}</a
    >{/if}{#if filters.offset + PAGE_SIZE < results.total}<a
      href={link('offset', String(filters.offset + PAGE_SIZE))}>{t.next} →</a
    >{/if}
</nav>
<p class="as-data">
  <span>{t.asData}</span>
  <code>GET /api/documents?{query}</code>
  <a href={`/api/documents?${query}`} target="_blank" rel="noreferrer">JSON ↗</a>
  <a href={href('/api', lang)}>{t.apiLink}</a>
</p>

<style>
  .list-note {
    margin: 0 0 var(--space-xs);
  }
  .document-filters {
    display: flex;
    flex-direction: column;
    gap: var(--space-md);
    margin: var(--space-2xl) 0;
  }
  .search-field {
    display: flex;
    gap: var(--space-md);
    align-items: center;
  }
  .search-field input {
    width: 100%;
    min-width: 0;
    padding: var(--space-md) 0;
    background: transparent;
    border: 0;
    border-bottom: var(--rule);
    color: var(--ink);
    font-size: var(--font-size-base);
  }
  .search-field button {
    font-size: var(--font-size-md);
    white-space: nowrap;
  }
  .selectors {
    display: grid;
    grid-template-columns: repeat(3, minmax(0, 1fr));
    gap: var(--space-md);
  }
  .selectors select {
    width: 100%;
    min-width: 0;
    font-size: var(--font-size-md);
  }
  .result-count {
    font-size: var(--font-size-sm);
    color: var(--muted);
    display: flex;
    justify-content: space-between;
    gap: var(--space-md);
    margin-bottom: var(--space-md);
  }
  .result-count a {
    text-decoration: underline;
  }
  .active-family {
    display: flex;
    align-items: center;
    gap: var(--space-xs);
    font-size: var(--font-size-md);
  }
  .active-family a {
    color: var(--muted);
    padding: 0 var(--space-2xs);
  }
  .active-family a:hover {
    color: var(--accent);
  }
  .swatch {
    width: var(--legend-key);
    height: var(--legend-key);
    background: var(--family);
  }
  .as-data {
    display: flex;
    flex-wrap: wrap;
    align-items: baseline;
    gap: var(--space-xs) var(--space-lg);
    font-size: var(--font-size-sm);
    color: var(--muted);
    border-top: var(--rule);
    padding-top: var(--space-lg);
  }
  .as-data code {
    font-family: var(--font-family-mono);
    background: var(--band);
    color: var(--ink);
    padding: var(--space-3xs) var(--space-xs);
    overflow-wrap: anywhere;
  }
  .as-data a {
    color: var(--ink);
    text-decoration: underline;
    text-underline-offset: var(--underline-offset);
  }
  .as-data a:hover {
    color: var(--accent);
  }
  .empty-state {
    padding: var(--space-5xl) 0;
  }
  .empty-state h2 {
    font-size: var(--font-size-xl);
    font-weight: var(--weight-book);
  }
  .empty-state p,
  .empty-state a {
    font-size: var(--font-size-base);
    margin-top: var(--space-lg);
    display: block;
  }
  .pagination {
    display: flex;
    justify-content: flex-end;
    gap: var(--space-3xl);
    padding: var(--space-2xl) 0;
    font-size: var(--font-size-base);
  }
  @media (max-width: 600px) {
    .selectors {
      grid-template-columns: minmax(0, 1fr);
    }
    .search-field button {
      padding: var(--space-md) var(--space-lg);
    }
    .pagination {
      padding: var(--space-lg) 0;
    }
  }
</style>
