<script lang="ts">
  import { page } from '$app/state';
  import { privacy } from '$lib/privacy';
  import { type Lang } from '$lib/i18n';
  let lang = $derived((page.params.lang || 'de') as Lang);
  let t = $derived(privacy[lang]);
</script>

<svelte:head>
  <title>{t.title} — OpenCommune</title>
  <meta name="description" content={t.intro} />
</svelte:head>

<article class="privacy-page container">
  <header>
    <h1>{t.title}</h1>
    <p class="updated">{t.updated}</p>
    <p class="intro">{t.intro}</p>
  </header>
  {#each t.sections as section}<section>
      <h2>{section.title}</h2>
      {#each section.paragraphs as paragraph}<p>{paragraph}</p>{/each}
    </section>{/each}
  <a class="text-link" href={`mailto:zdavid@ethz.ch?subject=${encodeURIComponent(t.title)}`}
    >{t.contact} ↗</a
  >
</article>

<style>
  .privacy-page {
    padding-block: var(--space-7xl) var(--space-8xl);
  }
  .privacy-page > * {
    max-width: var(--measure);
  }
  h1 {
    font-size: var(--font-size-page-title);
    line-height: var(--line-height-tight);
    letter-spacing: var(--letter-spacing-tight);
    margin-bottom: var(--space-xs);
  }
  .updated {
    color: var(--muted);
  }
  .intro {
    font-size: var(--font-size-2xl);
    line-height: var(--line-height-normal);
    margin-top: var(--space-xl);
  }
  section {
    margin-top: var(--space-4xl);
  }
  section h2 {
    margin-bottom: var(--space-md);
  }
  section p {
    line-height: var(--line-height-relaxed);
    margin-bottom: var(--space-md);
  }
  @media (max-width: 600px) {
    .privacy-page {
      padding-block: var(--space-4xl) var(--space-6xl);
    }
  }
</style>
