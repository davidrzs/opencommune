<script lang="ts">
  import { copy, href, fmt, type Lang } from '$lib/i18n';
  import { page } from '$app/state';
  let lang = $derived((page.params.lang || 'de') as Lang);
  let t = $derived(copy[lang]);
  const number = (n: number) => fmt(n, lang);
  import type { Commune } from './types';
  import { normalize } from './types';
  let { communes }: { communes: Commune[] } = $props();
  let query = $state('');
  let matches = $derived(
    query.trim()
      ? communes.filter((c) => normalize(c.name).includes(normalize(query))).slice(0, 8)
      : []
  );
</script>

<div class="commune-search">
  <label for="commune-search">{t.find}</label>
  <div class="search-line">
    <span aria-hidden="true">⌕</span><input
      id="commune-search"
      bind:value={query}
      placeholder={t.placeholder}
      autocomplete="off"
      type="search"
      aria-describedby="search-hint"
    />
  </div>
  {#if query.trim()}<div class="suggestions">
      <p id="search-hint" class="sr-only" aria-live="polite">{matches.length} {t.communes}</p>
      {#each matches as c}<a href={href(`/gemeinden/${c.bfs_id}`, lang)}
          ><span>{c.name} <small>{c.canton}</small></span><span
            >{c.minutes
              ? `${number(c.minutes)} ${t.minutesUnit}`
              : c.finance_years
                ? `${number(c.finance_years)} ${t.financeYears}`
                : c.decisions
                  ? `${number(c.decisions)} ${t.decisions}`
                  : ''} ↗</span
          ></a
        >{:else}<p>{t.noMatch}</p>{/each}
    </div>{:else}<span id="search-hint" class="sr-only">{t.find}.</span>{/if}
</div>
