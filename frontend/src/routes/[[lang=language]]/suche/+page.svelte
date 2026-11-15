<script lang="ts">
  import DocumentList from '$lib/DocumentList.svelte';
  import { page } from '$app/state';
  import { copy, type Lang } from '$lib/i18n';
  let { data } = $props();
  let lang = $derived((page.params.lang || 'de') as Lang);
  let t = $derived(copy[lang]);
</script>

<svelte:head
  ><title>{data.filters.q ? `${data.filters.q} — ` : ''}{t.search} — OpenCommune</title
  ></svelte:head
>
<section class="search-page container">
  <p class="eyebrow">{t.search}</p>
  <h1>{t.across}</h1>
  <p>{t.searchIntro}</p>
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
      {#if data.notice}<p class="search-notice" role="status">
          {data.notice === 'invalid' ? t.textInvalidWhy : t.textUnavailable}
        </p>{/if}
      <p>{t.textHelp}</p>
      <p>{t.textScope}</p>
    {/snippet}
  </DocumentList>
</section>

<style>
  p + p {
    margin-top: var(--space-2xs);
  }
  .search-notice {
    color: var(--notice);
    font-weight: var(--weight-medium);
  }
</style>
