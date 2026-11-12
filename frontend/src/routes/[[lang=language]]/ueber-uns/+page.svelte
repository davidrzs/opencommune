<script lang="ts">
  import { page } from '$app/state';
  import { about } from '$lib/about';
  import { type Lang } from '$lib/i18n';
  import ReportProblem from '$lib/ReportProblem.svelte';
  let lang = $derived((page.params.lang || 'de') as Lang);
  let t = $derived(about[lang]);
</script>

<svelte:head>
  <title>{t.title} — OpenCommune</title>
  <meta name="description" content={t.intro} />
</svelte:head>

<article class="about-page">
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
    max-width: 780px;
    margin: 0 auto;
    padding: 70px 24px 90px;
  }
  h1 {
    font-size: clamp(34px, 5vw, 54px);
    line-height: 1.1;
    letter-spacing: -1.5px;
  }
  .intro {
    font-size: 23px;
    line-height: 1.5;
    color: var(--ink);
    margin-top: 24px;
  }
  section {
    margin: 42px 0;
  }
  h2 {
    font-size: 23px;
    line-height: 1.3;
    margin-bottom: 16px;
  }
  p {
    font-size: 17px;
    line-height: 1.75;
    color: var(--muted);
    margin: 14px 0;
  }
  a {
    text-underline-offset: 4px;
  }
  @media (max-width: 600px) {
    .about-page {
      padding: 40px 20px 60px;
    }
  }
</style>
