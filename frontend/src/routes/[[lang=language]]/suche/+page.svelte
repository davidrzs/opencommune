<script lang="ts">
  import DocumentList from '$lib/DocumentList.svelte';
  import { page } from '$app/state';
  import { copy, type Lang } from '$lib/i18n';
  import { searchCopy } from '$lib/copy/search';
  let { data } = $props();
  let lang = $derived((page.params.lang || 'de') as Lang);
  let t = $derived(copy[lang]);
  let tips = $derived(searchCopy[lang].tips);
</script>

<svelte:head
  ><title>{data.filters.q ? `${data.filters.q} — ` : ''}{t.search} — Tractanda</title></svelte:head
>
<section class="search-page mx-auto max-w-7xl px-4 pt-8 sm:px-6">
  <h1 class="sr-only">{t.search}</h1>
  <DocumentList
    results={data.results}
    filters={data.filters}
    query={data.query}
    endpoint={data.endpoint}
    {lang}
    communes={data.communes}
    placeholder={t.textSearch}
    button={t.searchButton}
    empty={data.notice === 'invalid' ? t.textInvalid : undefined}
  >
    {#snippet help()}
      {#if data.notice}<p
          class="search-notice rounded-md bg-muted px-3 py-2 text-sm font-medium text-foreground"
          role="status"
        >
          {data.notice === 'invalid' ? t.textInvalidWhy : t.textUnavailable}
        </p>{/if}
      <!-- one line until opened: the results start right under the field -->
      <details class="search-tips">
        <summary class="w-fit cursor-pointer select-none hover:text-foreground">{tips}</summary>
        <div class="mt-1 space-y-1">
          <p>{t.textHelp}</p>
          <p>{t.textScope}</p>
        </div>
      </details>
    {/snippet}
  </DocumentList>
</section>
