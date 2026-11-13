<script lang="ts">
  import AccessNotice from '$lib/AccessNotice.svelte';
  import DocumentList from '$lib/DocumentList.svelte';
  import Holdings from '$lib/Holdings.svelte';
  import { filtered } from '$lib/documents';
  import { page } from '$app/state';
  import { copy, href, fmt, type Lang } from '$lib/i18n';
  import Map from '$lib/Map.svelte';
  let { data } = $props();
  let lang = $derived((page.params.lang || 'de') as Lang);
  let t = $derived(copy[lang]);
  let c = $derived(data.commune);
</script>

<svelte:head><title>{c.name} — OpenCommune</title></svelte:head>
<section class="commune-hero container">
  <a class="back-link" href={href('/', lang)}>← {t.back}</a>
  <div class="commune-heading">
    <div>
      <p class="eyebrow">{t.local} <span> / {c.canton}</span></p>
      <h1>{c.name}<span class="place-period">.</span></h1>
      <p>{t.scope}</p>
      {#if c.website}<a class="text-link" href={c.website} target="_blank" rel="noreferrer"
          >{t.official} ↗</a
        >{/if}
    </div>
    <!-- the access notice below shows the access state -->
    <div class="mini-map">
      <Map communes={[{ ...c, register_status: null, register_note: null }]} compact />
    </div>
  </div>
  <div class="commune-metrics">
    {#if c.documents}<span
        ><strong>{fmt(c.documents, lang)}</strong>
        {c.documents === 1 ? t.documentOne : t.documents}</span
      >{/if}<span class="subtle">{t.originalLanguage}</span>
  </div>
  <AccessNotice access={c.access || []} {lang} />
</section>
{#if c.holdings?.length}<Holdings holdings={c.holdings} filters={data.filters} {lang} />{/if}
<section class="archive-workspace container">
  <aside>
    <p class="eyebrow">{t.collection}</p>
    <p>{t.gaps}</p>
    <p class="small-note">{t.note}</p>
  </aside>
  <div class="document-list">
    <DocumentList
      results={data.results}
      filters={data.filters}
      query={data.query}
      {lang}
      commune={c.bfs_id}
      empty={c.documents === 0 && !filtered(data.filters) ? t.accessEmpty : undefined}
    />
  </div>
</section>
