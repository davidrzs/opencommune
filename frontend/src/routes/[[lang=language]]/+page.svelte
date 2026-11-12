<script lang="ts">
  import { copy, href, fmt, type Lang } from '$lib/i18n';
  import { page } from '$app/state';
  let lang = $derived((page.params.lang || 'de') as Lang);
  let t = $derived(copy[lang]);
  const number = (n: number) => fmt(n, lang);
  import Map from '$lib/Map.svelte';
  import CommuneSearch from '$lib/CommuneSearch.svelte';
  import { type Commune, type Coverage, type Findings, hasData, hasDocuments } from '$lib/types';
  import Chart from '$lib/Chart.svelte';
  import hfIcon from '$lib/icons/huggingface.svg';
  import ghIcon from '$lib/icons/github.svg';
  let { data } = $props();
  let coverage = $derived(data.coverage as Coverage | null);
  let held = $derived(Object.fromEntries((coverage?.communes ?? []).map((r) => [r.bfs_id, r])));
  let communes = $derived(
    (data.communes as Commune[]).map((c) => ({ ...c, ...(held[c.bfs_id] ?? {}) }))
  );
  let covered = $derived(communes.filter(hasData));
  let collected = $derived(communes.filter((c) => hasData(c) || hasDocuments(c)));
  const amount = (c: Commune) => (c.minutes ?? 0) + (c.finance_years ?? 0);
  let canton = $state('');
  let visibleCount = $state(50);
  let shown = $derived(
    communes
      .filter((c) => !canton || c.canton === canton)
      .sort(
        (a, b) =>
          amount(b) - amount(a) || b.documents - a.documents || a.name.localeCompare(b.name, lang)
      )
  );
  let cantons = $derived([...new Set(communes.map((c) => c.canton))].sort());
  let findings = $derived(data.findings as Findings | null);
  let years = $derived([...new Set((findings?.deficits || []).map((d) => d.year))].sort());
  const share = (type: string, year: number) => {
    const d = findings?.deficits.find((r) => r.type === type && r.year === year);
    return d ? (100 * d.deficit) / d.n : null;
  };
  const percent = (v: number) =>
    `${new Intl.NumberFormat(`${lang}-CH`, { maximumFractionDigits: 0 }).format(v)} %`;
  const sizeLabel = (lo: number, hi: number | null) =>
    hi === null ? `≥ ${lo / 1000}` : lo === 0 ? `< ${hi / 1000}` : `${lo / 1000}–${hi / 1000}`;
</script>

<svelte:head
  ><title>OpenCommune — {t.archive}</title><meta
    name="description"
    content={t.intro}
  /></svelte:head
>
<section class="atlas">
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
      <span><i class="key decisions"></i>{t.dataKey}</span><span
        ><i class="key documents"></i>{t.documentsKey}</span
      ><span><i class="key empty"></i>{t.missing}</span><span
        ><i class="key restricted"></i>{t.accessRestricted}</span
      >
    </div>
    <span class="map-credit">{t.borders}: swisstopo / swiss-maps</span>
  </div>
</section>
<nav class="resources" aria-label={t.dataset}>
  <a href="https://huggingface.co/datasets/davidrzs/opencommune"
    ><img src={hfIcon} alt="" />{t.dataset} ↗</a
  >
  <a href="https://github.com/davidrzs/opencommune"><img src={ghIcon} alt="" />{t.openSource} ↗</a>
</nav>
{#if findings}
  <section class="findings">
    <div class="findings-head">
      <p class="eyebrow">{t.findings}</p>
      <p class="small-note">{t.findingsNote}</p>
    </div>
    <div class="findings-grid">
      <figure>
        <h3>{t.deficitsTitle}</h3>
        <p>{t.deficitsText}</p>
        <div class="series-key">
          <span><i class="accent"></i>{t.budgets}</span><span><i></i>{t.accounts}</span>
        </div>
        <Chart
          labels={years.map(String)}
          series={[
            { label: t.budgets, values: years.map((y) => share('budget', y)), accent: true },
            { label: t.accounts, values: years.map((y) => share('accounts', y)) }
          ]}
          min={0}
          max={100}
          yTitle={t.shareDeficit}
          format={percent}
        />
      </figure>
      <figure>
        <h3>{t.turnoutTitle}</h3>
        <p>{t.turnoutText}</p>
        <Chart
          kind="bar"
          labels={findings.turnout_by_size.map((s) => sizeLabel(s.min, s.max))}
          series={[
            {
              label: t.turnoutAxis,
              values: findings.turnout_by_size.map((s) =>
                s.median === null ? null : 100 * s.median
              )
            }
          ]}
          yTitle={t.turnoutAxis}
          format={percent}
        />
      </figure>
    </div>
  </section>
{/if}
<section class="archive-index" id="gemeinden">
  <div class="index-intro">
    <h2>{t.dataFrom.replace('{count}', number(covered.length))}</h2>
    {#if coverage}<p>
        {t.dataStock
          .replace('{minutes}', number(coverage.totals.minutes))
          .replace('{counted}', number(coverage.totals.counted))
          .replace('{finance}', number(coverage.totals.communes_with_finance))
          .replace('{share}', percent(100 * (coverage.totals.population_share ?? 0)))}
      </p>{/if}
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
            >{[
              c.minutes ? `${number(c.minutes)} ${t.minutesUnit}` : '',
              c.finance_years ? `${number(c.finance_years)} ${t.financeYears}` : ''
            ]
              .filter(Boolean)
              .join(' · ')} <b>↗</b></span
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
    max-width: 1600px;
    margin: auto;
    padding: 26px 5% 0;
    border-top: 1px solid var(--line);
    display: flex;
    flex-wrap: wrap;
    gap: 12px 32px;
    font-size: 14px;
  }
  .resources a {
    display: inline-flex;
    align-items: center;
    gap: 8px;
    color: var(--ink);
    text-decoration: none;
  }
  .resources a:hover {
    color: var(--accent);
  }
  .resources img {
    height: 20px;
    width: auto;
  }
  .resources + .archive-index {
    border-top: 0;
  }
  .resources + .findings {
    border-top: 0;
    padding-top: 44px;
  }
  .findings {
    max-width: 1600px;
    margin: auto;
    padding: 65px 5% 40px;
    border-top: 1px solid var(--line);
  }
  .findings-head {
    display: grid;
    grid-template-columns: minmax(0, 1fr) minmax(0, 1.4fr);
    gap: 32px;
    align-items: start;
    margin-bottom: 36px;
  }
  .findings-grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(340px, 1fr));
    gap: 56px;
  }
  .findings figure {
    margin: 0;
  }
  .findings h3 {
    font-size: 28px;
    font-weight: 450;
    letter-spacing: -0.5px;
    margin-bottom: 8px;
  }
  .findings figure p {
    color: var(--muted);
    margin-bottom: 14px;
  }
  .series-key {
    display: flex;
    gap: 18px;
    font-size: 13px;
    color: var(--muted);
    margin-bottom: 4px;
  }
  .series-key i {
    display: inline-block;
    width: 14px;
    height: 2px;
    background: #3a3f47;
    margin-right: 6px;
    vertical-align: middle;
  }
  .series-key i.accent {
    background: var(--accent);
  }
  @media (max-width: 720px) {
    .findings {
      padding: 48px 5% 16px;
    }
    .findings-head {
      grid-template-columns: 1fr;
    }
  }
  .load-more {
    display: block;
    width: 100%;
    padding: 18px 6px;
    background: transparent;
    color: var(--ink);
    text-align: left;
    font-size: 14px;
    border: 0;
    text-decoration: underline;
    text-underline-offset: 4px;
  }
  .load-more:hover {
    background: transparent;
    color: var(--accent);
  }
</style>
