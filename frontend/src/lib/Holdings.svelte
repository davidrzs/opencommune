<script lang="ts">
  import { onMount } from 'svelte';
  import { page } from '$app/state';
  import type { Filters } from './documents';
  import { copy, documentCount, fmt, label, type Lang } from './i18n';
  import { FAMILIES, type CommuneDetail } from './types';
  // A commune's documents per year and family: years as columns, oldest left and newest right,
  // only the years the API lists (no gaps filled in); a cell links to the list filtered by both.
  let {
    holdings,
    filters,
    lang
  }: { holdings: CommuneDetail['holdings']; filters: Filters; lang: Lang } = $props();
  let t = $derived(copy[lang]);
  let years = $derived([...new Set(holdings.map((h) => h.year))].sort((a, b) => a - b));
  let counts = $derived(new Map(holdings.map((h) => [`${h.family} ${h.year}`, h.documents])));
  // a cell's colour strength: its count against the table's highest
  let most = $derived(Math.max(...holdings.map((h) => h.documents)));
  let scroller: HTMLDivElement;
  // the newest years are on the right: start there when the table is wider than the page
  onMount(() => scroller.scrollTo({ left: scroller.scrollWidth }));
</script>

<section class="holdings container" aria-labelledby="holdings-title">
  <h2 class="eyebrow" id="holdings-title">{t.holdingsTitle}</h2>
  <p class="small-note">{t.holdingsNote}</p>
  <div class="scroller" bind:this={scroller}>
    <table>
      <thead>
        <tr>
          <th></th>
          {#each years as year}<th scope="col">{year}</th>{/each}
        </tr>
      </thead>
      <tbody>
        {#each FAMILIES as family}<tr>
            <th scope="row" class="family-{family}">
              <i class="swatch" aria-hidden="true"></i>{label(lang, 'family', family)}
            </th>
            {#each years as year}{@const n = counts.get(`${family} ${year}`) ?? 0}<td>
                {#if n}<a
                    class="cell family-{family}"
                    class:active={filters.family === family && filters.year === String(year)}
                    href={`${page.url.pathname}?year=${year}&family=${family}`}
                    aria-label={`${label(lang, 'family', family)}, ${year}: ${documentCount(n, lang)}`}
                    style:--share={n / most}>{fmt(n, lang)}</a
                  >{/if}
              </td>{/each}
          </tr>{/each}
      </tbody>
    </table>
  </div>
</section>

<style>
  .holdings {
    padding-block: var(--space-3xl);
    border-top: var(--rule);
  }
  .small-note {
    margin: var(--space-xs) 0 var(--space-lg);
  }
  .scroller {
    overflow-x: auto;
    scrollbar-width: thin;
    scrollbar-color: var(--line-mid) transparent;
  }
  table {
    border-collapse: separate;
    border-spacing: var(--space-3xs);
    font-size: var(--font-size-sm);
  }
  th {
    font-weight: var(--weight-regular);
    color: var(--muted);
    white-space: nowrap;
  }
  thead th {
    font-size: var(--font-size-xs);
    padding-bottom: var(--space-2xs);
  }
  tbody th {
    text-align: left;
    padding-right: var(--space-md);
    color: var(--ink);
  }
  /* the family names stay in view while the years scroll */
  th:first-child {
    position: sticky;
    left: 0;
    z-index: var(--layer-above);
    background: var(--paper);
  }
  .swatch {
    display: inline-block;
    width: var(--legend-key);
    height: var(--legend-key);
    margin-right: var(--space-xs);
    background: var(--family);
  }
  td {
    padding: 0;
    min-width: var(--space-3xl);
  }
  .cell {
    display: grid;
    place-items: center;
    min-height: var(--space-3xl);
    color: var(--ink);
    background: color-mix(
      in srgb,
      var(--family)
        calc(
          var(--holdings-mix-min) + (var(--holdings-mix-max) - var(--holdings-mix-min)) *
            var(--share)
        ),
      var(--paper)
    );
  }
  .cell:hover,
  .cell.active {
    outline: var(--focus-ring);
    outline-offset: calc(-1 * var(--space-3xs));
  }
</style>
