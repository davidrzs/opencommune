<script lang="ts">
  import ReportProblem from '$lib/ReportProblem.svelte';
  import { page } from '$app/state';
  import { copy, fmt, href, when, type Lang } from '$lib/i18n';
  let { data } = $props();
  let lang = $derived((page.params.lang || 'de') as Lang);
  let t = $derived(copy[lang]);
</script>

<svelte:head><title>{t.search} — OpenCommune</title></svelte:head>
<section class="search-page">
  <p class="eyebrow">{t.search}</p>
  <h1>{t.across}</h1>
  <p>{t.searchIntro}</p>
  <p class="small-note">{t.extractionNote}</p>
  <form class="filters" method="GET">
    <input
      name="q"
      aria-label={t.decisionSearch}
      placeholder={t.decisionSearch}
      value={data.q}
    /><button>{t.search} ↗</button>
  </form>
  <p class="result-count">{fmt(data.results.total, lang)} {t.result}</p>
  {#each data.results.items as item}<article class="document-row">
      <div class="document-date">{when(item.meeting_date, lang)}</div>
      <div>
        <span class="document-kind">{item.commune.name} · {item.commune.canton}</span>
        <h2><a href={href(`/entscheide/${item.id}`, lang)}>{item.title}</a></h2>
        <p>{item.summary}</p>
        <a class="text-link" href={item.source_link} target="_blank" rel="noreferrer"
          >{t.original} ↗</a
        >
        <ReportProblem {lang} entry={item.id} source={item.source_link} />
      </div>
    </article>{:else}<h2>{t.noResults}</h2>{/each}
  <nav class="pagination" aria-label={t.result}>
    {#if data.offset > 0}<a href={`?q=${encodeURIComponent(data.q)}&offset=${data.offset - 20}`}
        >← {t.prev}</a
      >{/if}{#if data.offset + 20 < data.results.total}<a
        href={`?q=${encodeURIComponent(data.q)}&offset=${data.offset + 20}`}>{t.next} →</a
      >{/if}
  </nav>
</section>
