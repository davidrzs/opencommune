<script lang="ts">
  import DocumentList from '$lib/DocumentList.svelte';
  import { page } from '$app/state';
  import { copy, type Lang } from '$lib/i18n';
  let { data } = $props();
  let lang = $derived((page.params.lang || 'de') as Lang);
  let t = $derived(copy[lang]);
</script>

<svelte:head><title>{t.search} — OpenCommune</title></svelte:head>
<section class="search-page container">
  <p class="eyebrow">{t.search}</p>
  <h1>{t.across}</h1>
  <p>{t.searchIntro}</p>
  <DocumentList results={data.results} filters={data.filters} query={data.query} {lang} />
</section>
