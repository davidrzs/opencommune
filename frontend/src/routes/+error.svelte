<script lang="ts">
  import { page } from '$app/state';
  import { copy, href, type Lang } from '$lib/i18n';
  let lang = $derived((page.params.lang || 'de') as Lang);
  let t = $derived(copy[lang]);
</script>

<svelte:head><title>{page.status} · OpenCommune</title></svelte:head>

<section class="search-page container">
  <h1>{page.status}</h1>
  <p>{page.status === 404 ? t.noMatch : t.unavailable}</p>
  <a href={href('/', lang)}>OpenCommune →</a>
</section>
