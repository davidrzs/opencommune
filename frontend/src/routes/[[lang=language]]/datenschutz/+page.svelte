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

<article class="privacy-page">
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
    max-width: 780px;
    margin: 0 auto;
    padding: 70px 24px 90px;
  }
  h1 {
    font-size: clamp(34px, 5vw, 54px);
    line-height: 1.1;
    letter-spacing: -1.5px;
    margin-bottom: 6px;
  }
  .updated {
    color: var(--muted);
    margin-top: 0;
  }
  .intro {
    font-size: 21px;
    line-height: 1.5;
    margin-top: 18px;
  }
  section {
    margin-top: 36px;
  }
  section h2 {
    margin-bottom: 10px;
  }
  section p {
    line-height: 1.65;
    margin: 0 0 14px;
  }
</style>
