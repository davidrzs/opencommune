<script lang="ts">
  import { page } from '$app/state';
  import { about } from '$lib/about';
  import { documentCount, href, type Lang } from '$lib/i18n';
  import { privacy } from '$lib/privacy';
  import ReportProblem from '$lib/ReportProblem.svelte';
  let lang = $derived((page.params.lang || 'de') as Lang);
  let t = $derived(about[lang]);
  let { data } = $props();
</script>

<svelte:head>
  <title>{t.title} — OpenCommune</title>
  <meta name="description" content={t.intro} />
</svelte:head>

<article class="about-page container">
  <header>
    <h1>{t.title}</h1>
    <p class="intro">{t.intro}</p>
  </header>
  <section>
    <h2>{t.purposeTitle}</h2>
    <p>{t.purpose}</p>
    <p>{t.aim}</p>
  </section>
  <section>
    <h2>{t.sourcesTitle}</h2>
    <p>{t.sources}</p>
  </section>
  <section>
    <h2>{t.methodTitle}</h2>
    <p>{t.method}</p>
    <p>{t.limits}</p>
  </section>
  <section id="klassifikation">
    <h2>{t.classificationTitle}</h2>
    <p>{t.classification}</p>
    {#each data.runs ?? [] as run (run.id)}<div class="run" id={`run-${run.id}`}>
        <h3><code>{run.id}</code></h3>
        <p class="run-meta">
          {[run.model && `${t.model}: ${run.model}`, documentCount(run.documents, lang)]
            .filter(Boolean)
            .join(' · ')}
        </p>
        <p>{run.note}</p>
      </div>{/each}
  </section>
  <section>
    <h2>{t.dataTitle}</h2>
    <p>{t.data}</p>
    <ul class="data-links">
      <li>
        <a href={href('/api', lang)}>{t.api}</a>
      </li>
      <li>{t.mcp}: <code>{page.url.origin}/mcp</code></li>
      <li><a href="https://huggingface.co/datasets/davidrzs/opencommune">{t.dataset} ↗</a></li>
      <li><a href="/llms.txt">{t.llms}</a></li>
    </ul>
  </section>
  <section>
    <h2>{t.privacyTitle}</h2>
    <p>{t.privacy}</p>
    <a class="text-link" href={href('/datenschutz', lang)}>{privacy[lang].title} →</a>
  </section>
  <section>
    <h2>{t.teamTitle}</h2>
    <p>
      {t.team.split('David Zollikofer')[0]}<a href="https://www.davidrzs.com/">David Zollikofer</a
      >{t.team.split('David Zollikofer')[1]}
    </p>
    <p>{t.contact}</p>
    <ReportProblem {lang} mode="contact" />
  </section>
  <a class="text-link" href="https://github.com/davidrzs/opencommune">{t.sourceLink} ↗</a>
</article>

<style>
  .about-page {
    padding-block: var(--space-7xl) var(--space-8xl);
  }
  .about-page > * {
    max-width: var(--measure);
  }
  h1 {
    font-size: var(--font-size-page-title);
    line-height: var(--line-height-tight);
    letter-spacing: var(--letter-spacing-tight);
  }
  .intro {
    font-size: var(--font-size-2xl);
    line-height: var(--line-height-normal);
    color: var(--ink);
    margin-top: var(--space-2xl);
  }
  section {
    margin: var(--space-4xl) 0;
  }
  h2 {
    font-size: var(--font-size-2xl);
    line-height: var(--line-height-snug);
    margin-bottom: var(--space-lg);
  }
  p {
    font-size: var(--font-size-lg);
    line-height: var(--line-height-loose);
    color: var(--muted);
    margin: var(--space-md) 0;
  }
  a {
    text-underline-offset: var(--underline-offset);
  }
  .run {
    border-top: var(--rule);
    padding-top: var(--space-md);
    margin-top: var(--space-2xl);
  }
  .run h3 {
    font-size: var(--font-size-md);
    font-weight: var(--weight-medium);
    overflow-wrap: anywhere;
  }
  p.run-meta {
    font-size: var(--font-size-md);
    margin: var(--space-xs) 0;
  }
  .data-links {
    padding-left: var(--space-xl);
    line-height: var(--line-height-loose);
  }
  .data-links code {
    font-size: var(--font-size-code);
    overflow-wrap: anywhere;
  }
  @media (max-width: 600px) {
    .about-page {
      padding-block: var(--space-4xl) var(--space-6xl);
    }
  }
</style>
