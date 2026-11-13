<script lang="ts">
  import { page } from '$app/state';
  import { copy, fmt, href, when, type Lang } from '$lib/i18n';
  import ReportProblem from '$lib/ReportProblem.svelte';
  let { data } = $props();
  let lang = $derived((page.params.lang || 'de') as Lang);
  let t = $derived(copy[lang]);
  let d = $derived(data.decision);
  let outcome = $derived(d.outcome ? (t as Record<string, string>)[d.outcome] || d.outcome : '');
</script>

<svelte:head>
  <title>{d.title} — {d.commune.name} — OpenCommune</title>
  <meta name="description" content={d.summary} />
</svelte:head>

<article class="decision-page">
  <a class="text-link" href={href(`/gemeinden/${d.commune.bfs_id}?tab=decisions`, lang)}
    >← {d.commune.name} ({d.commune.canton})</a
  >
  <h1>{d.title}</h1>
  <p class="decision-meta">
    {when(
      d.meeting_date,
      lang
    )}{#if outcome}&ensp;·&ensp;{outcome}{/if}{#if d.amount_chf !== null}&ensp;·&ensp;CHF
      {fmt(Math.round(d.amount_chf), lang)}{/if}
  </p>
  <p class="summary">{d.summary}</p>
  <a class="text-link" href={d.source_link} target="_blank" rel="noreferrer">{t.original} ↗</a>
  <p class="small-note">{t.extractionNote}</p>
  <ReportProblem {lang} entry={d.id} source={d.source_link} />
</article>

<style>
  .decision-page {
    max-width: 780px;
    margin: 0 auto;
    padding: 56px 24px 90px;
  }
  h1 {
    font-size: clamp(28px, 4vw, 42px);
    line-height: 1.15;
    letter-spacing: -1px;
    margin: 18px 0 12px;
  }
  .decision-meta {
    color: var(--muted);
    margin: 0 0 22px;
  }
  .summary {
    font-size: 19px;
    line-height: 1.55;
  }
</style>
