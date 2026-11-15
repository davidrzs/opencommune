<script lang="ts">
  import type { Snippet } from 'svelte';
  import { goto } from '$app/navigation';
  import { page } from '$app/state';
  import DocumentRow from './DocumentRow.svelte';
  import { FILTERS, TEXT_CAP, filtered, type Filters } from './documents';
  import { copy, fmt, href, label, type Lang } from './i18n';
  import {
    BODY_KINDS,
    SECTION_TYPES,
    type Commune,
    type DocumentPage,
    type TextPage
  } from './types';
  // `commune`: the commune page's commune; without it the list spans every commune. `query`: the
  // API query the page loaded the list with, from `endpoint`. Results of /api/pages (a full-text
  // search) show each file's matching pages and offer the canton and commune filters.
  // `placeholder`, `button` and `help`: the text field's placeholder, its button and a help line
  // under it. `communes`: every commune, to name the commune filter.
  let {
    results,
    filters,
    query,
    lang,
    commune,
    empty,
    endpoint = '/api/documents',
    placeholder,
    button,
    help,
    communes = []
  }: {
    results: DocumentPage | TextPage;
    filters: Filters;
    query: string;
    lang: Lang;
    commune?: number;
    empty?: string;
    endpoint?: string;
    placeholder?: string;
    button?: string;
    help?: Snippet;
    communes?: Commune[];
  } = $props();
  let t = $derived(copy[lang]);
  let form: HTMLFormElement;
  let text = $derived('capped' in results ? results : null);

  // One selector per facet. Values in the vocabulary's order, else in the API's order (years
  // newest first, cantons by code, communes with the most files first); a value without a filter
  // of its own (null: no year, no body, ...) is listed with its count but not selectable.
  type Key = 'section' | 'body' | 'year' | 'canton' | 'commune';
  type Option = { value: string | number | null; count: number | null };
  type Selector = {
    key: Key;
    name: string;
    all: string;
    facet: Option[];
    order: readonly string[] | null;
  };
  let selectors = $derived.by((): Selector[] => {
    const section: Selector = {
      key: 'section',
      name: t.sectionLabel,
      all: t.allSections,
      facet: results.facets.sections,
      order: SECTION_TYPES
    };
    const year: Selector = {
      key: 'year',
      name: t.yearLabel,
      all: t.allYears,
      facet: results.facets.years,
      order: null
    };
    const body = { key: 'body' as Key, name: t.bodyLabel, all: t.allBodies, order: BODY_KINDS };
    if (!text) return [section, { ...body, facet: (results as DocumentPage).facets.bodies }, year];
    // a full-text search counts no bodies; it leaves out the documents of private bodies
    const bodies = BODY_KINDS.filter((b) => b !== 'private').map((value) => ({
      value,
      count: null
    }));
    return [
      section,
      { ...body, facet: bodies },
      year,
      {
        key: 'canton',
        name: t.cantonLabel,
        all: t.allCantons,
        facet: text.facets.cantons,
        order: null
      },
      {
        key: 'commune',
        name: t.commune,
        all: t.allCommunes,
        facet: text.facets.communes.map((c) => ({ value: c.bfs_id, count: c.count })),
        order: null
      }
    ];
  });
  function options(key: Key, facet: Option[], order: readonly string[] | null) {
    const rank = (f: Option) =>
      f.value === null
        ? Infinity
        : order
          ? order.indexOf(String(f.value)) + 1 || order.length + 1
          : 0;
    const listed = [...facet].sort((a, b) => rank(a) - rank(b));
    // the chosen value stays visible when the other filters leave nothing of it
    if (filters[key] && !listed.some((f) => String(f.value) === filters[key]))
      listed.unshift({ value: filters[key], count: 0 });
    return listed;
  }
  const communeName = (bfs: string) =>
    text?.facets.communes.find((c) => String(c.bfs_id) === bfs)?.name ??
    communes.find((c) => String(c.bfs_id) === bfs)?.name ??
    bfs;
  const name = (key: Key, value: string | number | null) =>
    value === null
      ? t.noValue
      : key === 'year' || key === 'canton'
        ? String(value)
        : key === 'commune'
          ? communeName(String(value))
          : label(lang, key, value);

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
    <input
      name="q"
      aria-label={placeholder ?? t.docSearch}
      placeholder={placeholder ?? t.docSearch}
      aria-describedby={help ? 'search-help' : undefined}
      maxlength="500"
      value={filters.q}
    /><button>{button ?? t.filter} ↗</button>
  </div>
  {#if help}<div class="search-help" id="search-help">{@render help()}</div>{/if}
  {#if filters.family}<p class="active-filter active-family family-{filters.family}">
      <input type="hidden" name="family" value={filters.family} /><i
        class="swatch"
        aria-hidden="true"
      ></i>{t.familyLabel}
      {label(lang, 'family', filters.family)}
      <a href={link('family', '')} aria-label={t.removeFilter} title={t.removeFilter}>×</a>
    </p>{/if}
  {#if !text && commune === undefined && filters.commune}<p class="active-filter active-commune">
      <input type="hidden" name="commune" value={filters.commune} />{t.communeFilter.replace(
        '{name}',
        communeName(filters.commune)
      )}
      <a href={link('commune', '')} aria-label={t.removeFilter} title={t.removeFilter}>×</a>
    </p>{/if}
  <div class="selectors">
    {#each selectors as s (s.key)}<select
        name={s.key}
        aria-label={s.name}
        value={filters[s.key]}
        onchange={() => form.requestSubmit()}
        ><option value="">{s.all}</option>{#each options(s.key, s.facet, s.order) as f}<option
            value={f.value === null ? '' : String(f.value)}
            disabled={f.value === null}
            >{name(s.key, f.value)}{f.count === null ? '' : ` (${fmt(f.count, lang)})`}</option
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
{#if text?.capped}<p class="capped">{t.capped.replaceAll('{n}', fmt(TEXT_CAP, lang))}</p>{/if}
{#each results.items as doc (doc.sha256)}<DocumentRow
    {doc}
    {lang}
    {commune}
    section={text ? '' : filters.section}
    family={text ? '' : filters.family}
    hits={'pages' in doc ? doc.pages : undefined}
    matching={'matching_pages' in doc ? doc.matching_pages : undefined}
  />{:else}<div class="empty-state">
    <h2>{empty ?? t.noResults}</h2>
    {#if filters.year}<p>{t.unknownDate}</p>{/if}{#if filtered(filters)}<a href={page.url.pathname}
        >{t.reset}</a
      >{/if}
  </div>{/each}
<nav class="pagination" aria-label={t.result}>
  {#if filters.offset > 0}<a
      href={link(
        'offset',
        filters.offset > results.limit ? String(filters.offset - results.limit) : ''
      )}>← {t.prev}</a
    >{/if}{#if filters.offset + results.limit < results.total}<a
      href={link('offset', String(filters.offset + results.limit))}>{t.next} →</a
    >{/if}
</nav>
<p class="as-data">
  <span>{t.asData}</span>
  <code>GET {endpoint}?{query}</code>
  <a href={`${endpoint}?${query}`} target="_blank" rel="noreferrer">JSON ↗</a>
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
  .search-help {
    font-size: var(--font-size-sm);
    line-height: var(--line-height-relaxed);
    color: var(--muted);
    max-width: var(--measure);
  }
  .capped {
    font-size: var(--font-size-sm);
    line-height: var(--line-height-relaxed);
    color: var(--notice);
    margin-bottom: var(--space-md);
  }
  .active-filter {
    display: flex;
    align-items: center;
    gap: var(--space-xs);
    font-size: var(--font-size-md);
  }
  .active-filter a {
    color: var(--muted);
    padding: 0 var(--space-2xs);
  }
  .active-filter a:hover {
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
