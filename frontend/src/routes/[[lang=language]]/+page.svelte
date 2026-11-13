<script lang="ts">
  import { copy, documentCount, href, fmt, type Lang } from '$lib/i18n';
  import { page } from '$app/state';
  let lang = $derived((page.params.lang || 'de') as Lang);
  let t = $derived(copy[lang]);
  const number = (n: number) => fmt(n, lang);
  import Map from '$lib/Map.svelte';
  import CommuneSearch from '$lib/CommuneSearch.svelte';
  import { type Commune, hasDocuments } from '$lib/types';
  import hfIcon from '$lib/icons/huggingface.svg';
  import ghIcon from '$lib/icons/github.svg';
  let { data } = $props();
  let communes = $derived(data.communes as Commune[]);
  let collected = $derived(communes.filter(hasDocuments));
  let canton = $state('');
  let visibleCount = $state(50);
  let shown = $derived(
    communes
      .filter((c) => !canton || c.canton === canton)
      .sort((a, b) => b.documents - a.documents || a.name.localeCompare(b.name, lang))
  );
  let cantons = $derived([...new Set(communes.map((c) => c.canton))].sort());
</script>

<svelte:head
  ><title>OpenCommune — {t.archive}</title><meta
    name="description"
    content={t.intro}
  /></svelte:head
>
<section class="atlas container">
  <div class="atlas-top">
    <p class="eyebrow">{t.archive}</p>
    <span class="edition">Schweiz / Suisse / Svizzera</span>
  </div>
  <div class="atlas-intro">
    <div>
      <h1>{t.title}<br /><em>{t.subtitle}</em></h1>
      <p>{t.intro}<br />{t.intro2}</p>
      <p class="coverage-count">
        <a href="#gemeinden"><strong>{number(collected.length)}</strong> {t.withDocuments}</a>
      </p>
    </div>
    <CommuneSearch {communes} />
  </div>
  <Map {communes} />
  <div class="atlas-bottom">
    <div class="legend">
      <span><i class="key documents"></i>{t.documentsKey}</span><span
        ><i class="key empty"></i>{t.missing}</span
      ><span><i class="key restricted"></i>{t.accessRestricted}</span>
    </div>
    <span class="map-credit">{t.borders}: swisstopo / swiss-maps</span>
  </div>
</section>
<nav class="resources container" aria-label={t.dataset}>
  <a href="https://huggingface.co/datasets/davidrzs/opencommune"
    ><img src={hfIcon} alt="" />{t.dataset} ↗</a
  >
  <a href="https://github.com/davidrzs/opencommune"><img src={ghIcon} alt="" />{t.openSource} ↗</a>
</nav>
<section class="archive-index container" id="gemeinden">
  <div class="index-intro">
    {#await data.files then files}{#if files !== null}<h2>
          {t.archiveTotal
            .replace('{documents}', number(files))
            .replace('{communes}', number(collected.length))}
        </h2>{/if}{/await}
    <p class="small-note">{t.coverageNote}</p>
    <a class="text-link" href={href('/suche', lang)}>{t.topicLink} <span>↗</span></a>
  </div>
  <div class="commune-index">
    <div class="list-heading">
      <h3>{t.discover}</h3>
      <label
        ><span class="sr-only">{t.allCantons}</span><select
          bind:value={canton}
          onchange={() => (visibleCount = 50)}
          ><option value="">{t.allCantons}</option>{#each cantons as c}<option>{c}</option
            >{/each}</select
        ></label
      >
    </div>
    <div class="index-scroll">
      {#each shown.slice(0, visibleCount) as c}<a
          class="commune-row"
          href={href(`/gemeinden/${c.bfs_id}`, lang)}
          ><span>{c.name} <small>{c.canton}</small></span><span
            >{c.documents ? documentCount(c.documents, lang) : t.missing} <b>↗</b></span
          ></a
        >{/each}
      {#if visibleCount < shown.length}
        <button class="load-more" onclick={() => (visibleCount += 50)}>{t.moreCommunes} ↓</button>
      {/if}
    </div>
    <p class="small-note">{number(shown.length)} {t.communes}</p>
  </div>
</section>

<style>
  .resources {
    padding-top: var(--space-2xl);
    border-top: var(--rule);
    display: flex;
    flex-wrap: wrap;
    gap: var(--space-md) var(--space-3xl);
    font-size: var(--font-size-md);
  }
  .resources a {
    display: inline-flex;
    align-items: center;
    gap: var(--space-sm);
    color: var(--ink);
    text-decoration: none;
  }
  .resources a:hover {
    color: var(--accent);
  }
  .resources img {
    height: var(--icon-size);
    width: auto;
  }
  .load-more {
    display: block;
    width: 100%;
    padding: var(--space-lg) var(--space-xs);
    background: transparent;
    color: var(--ink);
    text-align: left;
    font-size: var(--font-size-md);
    border: 0;
    text-decoration: underline;
    text-underline-offset: var(--underline-offset);
  }
  .load-more:hover {
    background: transparent;
    color: var(--accent);
  }
</style>
