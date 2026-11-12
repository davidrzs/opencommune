<script lang="ts">
  import '../app.css';
  import { about } from '$lib/about';
  import ReportProblem from '$lib/ReportProblem.svelte';
  import { page } from '$app/state';
  import { copy, href, type Lang } from '$lib/i18n';
  let { children } = $props();
  let lang = $derived((page.params.lang || 'de') as Lang);
  let t = $derived(copy[lang]);
  $effect(() => {
    document.documentElement.lang = lang;
  });
  const languages: Lang[] = ['de', 'fr', 'it'];
  function switchTo(next: Lang) {
    return (
      href(page.url.pathname.replace(/^\/(de|fr|it)(?=\/|$)/, '') || '/', next) + page.url.search
    );
  }
</script>

<a class="skip" href="#main">{t.skip}</a>
<p class="wip">{t.wip} <ReportProblem {lang} /></p>
<header class="site-header">
  <a class="brand" href={href('/', lang)} aria-label="OpenCommune"
    ><svg class="brand-symbol" viewBox="0 0 32 32" aria-hidden="true" focusable="false"
      ><path fill="white" d="M13 6h6v7h7v6h-7v7h-6v-7H6v-6h7z" /></svg
    >OpenCommune<span class="brand-dot">.</span></a
  >
  <nav aria-label={t.archive}>
    <a
      href={href('/', lang)}
      aria-current={page.url.pathname === href('/', lang) ||
      page.url.pathname.includes('/gemeinden/')
        ? 'page'
        : undefined}>{t.communes}</a
    ><a
      href={href('/suche', lang)}
      aria-current={page.url.pathname.includes('/suche') ? 'page' : undefined}>{t.search}</a
    ><a
      href="https://github.com/davidrzs/opencommune/blob/main/server/API.md"
      target="_blank"
      rel="noreferrer">API ↗</a
    >
    <div class="languages" role="group" aria-label="Sprache / Langue / Lingua">
      {#each languages as l}<a
          href={switchTo(l)}
          hreflang={l}
          aria-current={lang === l ? 'true' : undefined}>{l.toUpperCase()}</a
        >{/each}
    </div>
  </nav>
</header>
<main id="main">{@render children()}</main>
<footer class="site-footer">
  <div>
    <a class="footer-brand" href={href('/', lang)}>OpenCommune.</a>
    <p>{t.footer}</p>
    <p class="maintainer">
      {t.maintainedBy} <a href="https://www.davidrzs.com/">David Zollikofer</a>
    </p>
  </div>
  <p>
    {t.disclaimer}
  </p>
  <div>
    <a href={href('/ueber-uns', lang)}>{about[lang].title}</a><br />
    <ReportProblem {lang} /><br /><a href="https://github.com/davidrzs/opencommune"
      >{t.openSource} ↗</a
    ><br /><a href="https://huggingface.co/datasets/davidrzs/opencommune">{t.dataset} ↗</a>
  </div>
</footer>
