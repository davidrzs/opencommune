<script lang="ts">
  import AccessNotice from '$lib/AccessNotice.svelte';
  import ReportProblem from '$lib/ReportProblem.svelte';
  import { page } from '$app/state';
  import { copy, href, fmt, when, type Lang } from '$lib/i18n';
  import Map from '$lib/Map.svelte';
  import Chart from '$lib/Chart.svelte';
  import type { CommuneDataset, DatasetVote } from '$lib/types';
  let { data } = $props();
  let ds = $derived(data.dataset as CommuneDataset | null);
  let shownVotes = $derived(
    (ds?.votes || []).filter((v) => !v.formal && (v.outcome || v.votes_yes !== null))
  );
  let voteLimit = $state(30);
  let withheld = $derived(shownVotes.filter((v) => v.title_withheld).length);
  let listed = $derived(shownVotes.filter((v) => !v.title_withheld));
  let fyears = $derived([...new Set((ds?.finance || []).map((f) => f.fiscal_year))].sort());
  let hasDataset = $derived(Boolean(ds && (ds.votes.length || ds.finance.length)));
  const fin = (type: string, y: number) =>
    ds?.finance.find((f) => f.type === type && f.fiscal_year === y) || null;
  const mio = (f: { operating_result: number | null } | null) =>
    f && f.operating_result !== null ? f.operating_result / 1e6 : null;
  const num2 = (v: number) =>
    new Intl.NumberFormat(`${lang}-CH`, { minimumFractionDigits: 2, maximumFractionDigits: 2 })
      .format(v)
      .replace('-', '−');
  let latestTax = $derived(
    [...(ds?.finance || [])].reverse().find((f) => f.tax_rate_percent !== null) || null
  );
  const outcome = (v: DatasetVote) =>
    v.outcome ? (t as Record<string, string>)[v.outcome] || v.outcome : '';
  const method = (v: DatasetVote) =>
    v.votes_yes !== null || v.votes_no !== null
      ? `${v.votes_yes ?? '?'} : ${v.votes_no ?? '?'}`
      : (t as Record<string, string>)[v.vote_method || ''] || '';
  let lang = $derived((page.params.lang || 'de') as Lang);
  let t = $derived(copy[lang]);
  let c = $derived(data.commune);
  function link(changes: Record<string, string>) {
    const p = new URLSearchParams(page.url.searchParams);
    for (const [k, v] of Object.entries(changes)) {
      if (v) p.set(k, v);
      else p.delete(k);
    }
    return `?${p}`;
  }
</script>

<svelte:head><title>{c.name} — OpenCommune</title></svelte:head>
<section class="commune-hero">
  <a class="back-link" href={href('/', lang)}>← {t.back}</a>
  <div class="commune-heading">
    <div>
      <p class="eyebrow">{t.local} <span> / {c.canton}</span></p>
      <h1>{c.name}<span class="place-period">.</span></h1>
      <p>{t.scope}</p>
      <a class="text-link" href={c.website} target="_blank" rel="noreferrer">{t.official} ↗</a>
    </div>
    <!-- the access notice below shows the access state -->
    <div class="mini-map"><Map communes={[{ ...c, access: undefined }]} compact /></div>
  </div>
  <div class="commune-metrics">
    {#if c.documents}<span><strong>{fmt(c.documents, lang)}</strong> {t.documents}</span
      >{/if}{#if c.decisions}<span><strong>{fmt(c.decisions, lang)}</strong> {t.decisions}</span
      >{/if}{#if ds && ds.summary.meetings}<span
        ><strong>{fmt(ds.summary.meetings, lang)}</strong> {t.minutesUnit}</span
      >{/if}{#if fyears.length}<span
        ><strong>{fmt(fyears.length, lang)}</strong> {t.financeYears}</span
      >{/if}{#if ds && ds.summary.median_turnout !== null}<span
        ><strong
          >{new Intl.NumberFormat(`${lang}-CH`, { maximumFractionDigits: 1 }).format(
            100 * ds.summary.median_turnout
          )} %</strong
        >
        {t.medianTurnout}</span
      >{/if}{#if ds && ds.summary.counted}<span
        ><strong>{fmt(ds.summary.counted, lang)}</strong> {t.countedVotes}</span
      >{/if}{#if latestTax}<span
        ><strong>{fmt(latestTax.tax_rate_percent || 0, lang)} %</strong>
        {t.taxRate}
        {latestTax.fiscal_year}</span
      >{/if}<span class="subtle">{t.originalLanguage}</span>
  </div>
  <AccessNotice access={c.access || []} {lang} />
</section>
<section class="archive-workspace">
  <aside>
    <p class="eyebrow">{t.collection}</p>
    <p>{t.gaps}</p>
    <p class="small-note">{t.note}</p>
  </aside>
  <div class="document-list">
    <nav class="tabs" aria-label={t.collection}>
      {#if c.documents || !hasDataset}<a
          class:active={data.tab === 'documents'}
          href={link({ tab: 'documents', offset: '', q: '', year: '' })}
          >{t.documents} <small>{fmt(c.documents, lang)}</small></a
        >{/if}{#if c.decisions}<a
          class:active={data.tab === 'decisions'}
          href={link({ tab: 'decisions', offset: '', q: '', year: '' })}
          >{t.decisions} <small>{fmt(c.decisions, lang)}</small></a
        >{/if}{#if ds && ds.votes.length}<a
          class:active={data.tab === 'votes'}
          href={link({ tab: 'votes', offset: '', q: '', year: '' })}
          >{t.votes} <small>{fmt(shownVotes.length, lang)}</small></a
        >{/if}{#if ds && ds.finance.length}<a
          class:active={data.tab === 'finance'}
          href={link({ tab: 'finance', offset: '', q: '', year: '' })}
          >{t.finance} <small>{fmt(fyears.length, lang)}</small></a
        >{/if}
    </nav>
    {#if data.tab === 'votes' && ds}
      <p class="small-note">{t.votesNote}</p>
      <div class="result-count">
        {t.rejectedOf
          .replace('{r}', fmt(ds.summary.rejected, lang))
          .replace('{n}', fmt(ds.summary.decided, lang))}
      </div>
      {#each listed.slice(0, voteLimit) as v}<article class="document-row vote-row">
          <div class="document-date">{when(v.meeting_date, lang)}</div>
          <div>
            <span class="document-kind">{v.motion ? t.motion : t.item}</span>
            <h2>{v.title}</h2>
          </div>
          <div class="vote-result" class:rejected={v.outcome === 'rejected'}>
            <strong>{outcome(v)}</strong><span>{method(v)}</span>
          </div>
        </article>{:else}<div class="empty-state"><h2>{t.noVotes}</h2></div>{/each}
      {#if voteLimit < listed.length}<button class="load-more" onclick={() => (voteLimit += 30)}
          >{t.moreVotes} ↓</button
        >{/if}
      {#if withheld}<p class="small-note">{fmt(withheld, lang)} × {t.withheld}</p>{/if}
    {:else if data.tab === 'finance' && ds}
      <h3 class="panel-title">{t.financeTitle}</h3>
      <p class="small-note">{t.financeText}</p>
      <div class="series-key">
        <span><i></i>{t.accountsOne}</span><span><i class="accent"></i>{t.budget}</span>
      </div>
      <Chart
        labels={fyears.map(String)}
        series={[
          { label: t.accountsOne, values: fyears.map((y) => mio(fin('accounts', y))) },
          { label: t.budget, values: fyears.map((y) => mio(fin('budget', y))), accent: true }
        ]}
        yTitle={t.mio}
        format={num2}
        width={960}
      />
      <table class="finance-table">
        <thead
          ><tr
            ><th>{t.year}</th><th class="n">{t.budget}</th><th class="n">{t.accountsOne}</th><th
              >{t.sourceDoc}</th
            ></tr
          ></thead
        >
        <tbody>
          {#each [...fyears].reverse() as y}
            {@const b = fin('budget', y)}{@const a = fin('accounts', y)}
            <tr>
              <td>{y}</td>
              {#each [b, a] as f}<td class="n"
                  >{#if mio(f) !== null}{num2(mio(f)!)}{:else}–{/if}</td
                >{/each}
              <td
                >{#if a?.source_url}<a
                    class="text-link"
                    href={a.source_url}
                    target="_blank"
                    rel="noreferrer">{t.accountsOne} ↗</a
                  >{/if}
                {#if b?.source_url}<a
                    class="text-link"
                    href={b.source_url}
                    target="_blank"
                    rel="noreferrer">{t.budget} ↗</a
                  >{/if}</td
              >
            </tr>
          {/each}
        </tbody>
      </table>
    {:else}
      {#if data.tab === 'decisions'}<p class="small-note">{t.extractionNote}</p>{/if}
      <form class="filters" method="GET">
        <input type="hidden" name="tab" value={data.tab} /><input
          name="q"
          aria-label={data.tab === 'documents' ? t.docSearch : t.decisionSearch}
          placeholder={data.tab === 'documents' ? t.docSearch : t.decisionSearch}
          value={data.q}
        />{#if data.tab === 'documents'}<select
            name="year"
            aria-label={t.allYears}
            value={data.year}
            ><option value="">{t.allYears}</option>{#each data.results.years as year}<option
                value={year}>{year}</option
              >{/each}</select
          >{/if}<button>{t.filter} ↗</button>
      </form>
      <div class="result-count">
        {fmt(data.results.total, lang)}
        {t.result}{#if data.q || data.year}<a href={link({ q: '', year: '', offset: '' })}
            >{t.reset}</a
          >{/if}
      </div>
      {#each data.results.items as item}<article class="document-row">
          <div class="document-date">{when(item.date || item.meeting_date, lang)}</div>
          <div>
            <span class="document-kind"
              >{data.tab === 'documents'
                ? item.decisions
                  ? t.extracted
                  : t.untagged
                : t.decisions}</span
            >
            <h2>
              {#if data.tab === 'decisions'}<a href={href(`/entscheide/${item.id}`, lang)}
                  >{item.title}</a
                >{:else}{item.title === 'Gemeindedokument' ? t.document : item.title}{/if}
            </h2>
            {#if item.summary}<p>{item.summary}</p>{/if}<a
              class="text-link"
              href={item.url || item.source_link}
              target="_blank"
              rel="noreferrer">{t.original} ↗</a
            >
            <ReportProblem {lang} entry={item.id} source={item.url || item.source_link} />
          </div>
          {#if data.tab === 'documents'}<span class="file-mark" aria-hidden="true">PDF</span>{/if}
        </article>{:else}<div class="empty-state">
          <h2>{c.documents === 0 ? t.accessEmpty : t.noResults}</h2>
          {#if data.year}<p>{t.unknownDate}</p>{/if}<a href={link({ q: '', year: '', offset: '' })}
            >{t.reset}</a
          >
        </div>{/each}
      <nav class="pagination" aria-label={t.result}>
        {#if data.offset > 0}<a href={link({ offset: String(Math.max(0, data.offset - 20)) })}
            >← {t.prev}</a
          >{/if}{#if data.offset + 20 < data.results.total}<a
            href={link({ offset: String(data.offset + 20) })}>{t.next} →</a
          >{/if}
      </nav>
    {/if}
  </div>
</section>

<style>
  .vote-row {
    grid-template-columns: 150px minmax(0, 1fr) 190px;
  }
  .vote-result {
    text-align: right;
    font-size: 14px;
  }
  .vote-result strong {
    display: block;
    font-weight: 550;
  }
  .vote-result span {
    color: var(--muted);
  }
  .vote-result.rejected strong {
    color: var(--accent);
  }
  .panel-title {
    font-size: 22px;
    font-weight: 500;
    margin: 28px 0 6px;
  }
  .series-key {
    display: flex;
    gap: 18px;
    font-size: 13px;
    color: var(--muted);
    margin: 10px 0 2px;
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
  .finance-table {
    width: 100%;
    border-collapse: collapse;
    margin: 18px 0 10px;
    font-size: 14px;
  }
  .finance-table th,
  .finance-table td {
    text-align: left;
    padding: 10px 6px;
    border-bottom: 1px solid var(--line);
  }
  .finance-table th {
    color: var(--muted);
    font-weight: 500;
  }
  .finance-table .n {
    text-align: right;
    font-variant-numeric: tabular-nums;
  }
  .finance-table .text-link {
    margin-right: 12px;
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
  @media (max-width: 720px) {
    .vote-row {
      grid-template-columns: 1fr;
    }
    .vote-result {
      text-align: left;
    }
  }
</style>
