<script lang="ts">
  import ReportProblem from './ReportProblem.svelte';
  import { originalLink } from './documents';
  import { copy, fmt, href, label, when, type Lang } from './i18n';
  import type { Document, Section } from './types';
  // `commune`: the commune whose page lists the file; its link to the original is used, and the
  // file's communes are named only when there are several. `section` and `family`: the list's
  // filters; the sections they match get a line of their own.
  let {
    doc,
    lang,
    commune,
    section = '',
    family = ''
  }: { doc: Document; lang: Lang; commune?: number; section?: string; family?: string } = $props();
  let t = $derived(copy[lang]);
  const pagesOf = (s: Section) => s.last_page - s.first_page + 1;
  const name = (s: Section) => label(lang, 'section', s.type);
  const range = (s: Section) =>
    `${t.pageAbbr} ${
      s.first_page === s.last_page
        ? fmt(s.first_page, lang)
        : `${fmt(s.first_page, lang)}–${fmt(s.last_page, lang)}`
    }`;
  // the date; else, for a budget or accounts, the fiscal year; else the year
  let fiscal = $derived(doc.sections.some((s) => s.type === 'budget' || s.type === 'accounts'));
  let dated = $derived(
    doc.date && !Number.isNaN(Date.parse(doc.date))
      ? when(doc.date, lang)
      : doc.year === null
        ? t.undated
        : fiscal
          ? t.fiscalYear.replace('{year}', String(doc.year))
          : String(doc.year)
  );
  // the title as printed; else the largest section's type and the year; else "document"
  let largest = $derived(
    doc.sections.reduce<Section | null>((a, s) => (!a || pagesOf(s) > pagesOf(a) ? s : a), null)
  );
  let title = $derived(
    doc.title?.trim() ||
      (largest
        ? [name(largest), doc.year].filter((part) => part !== null).join(' ')
        : t.documentOne)
  );
  let pages = $derived(
    doc.page_count === null
      ? ''
      : doc.page_count === 1
        ? t.onePage
        : t.pages.replace('{n}', fmt(doc.page_count, lang))
  );
  let meta = $derived([doc.body_name, pages].filter(Boolean).join(' · '));
  // languages only when they are not just the page's own
  let languages = $derived(
    doc.languages.length === 1 && doc.languages[0] === lang ? [] : doc.languages
  );
  // "Invitation, 2 × Proposal, Budget": each type once, in the order it first appears; news left out
  let contains = $derived(
    Object.entries(
      doc.sections
        .filter((s) => s.type !== 'news')
        .reduce<Record<string, number>>((counts, s) => {
          counts[s.type] = (counts[s.type] ?? 0) + 1;
          return counts;
        }, {})
    )
      .map(([type, n]) => {
        const named = label(lang, 'section', type);
        return n > 1 ? `${n} × ${named}` : named;
      })
      .join(', ')
  );
  // the strip spans the file's pages, or the last page a section names if that is further
  let total = $derived(Math.max(doc.page_count ?? 0, ...doc.sections.map((s) => s.last_page)));
  const tip = (s: Section) =>
    [`${name(s)}, ${range(s)}`, s.partly_unseen ? t.partlyUnseen : ''].filter(Boolean).join(' · ');
  // the content view: the sections the list is filtered by
  let matches = $derived(
    section || family
      ? doc.sections.filter(
          (s) => (!section || s.type === section) && (!family || s.family === family)
        )
      : []
  );
  let unseen = $derived(doc.sections.some((s) => s.partly_unseen));
  // the original through this site, at the address of the listing commune, else of the file's
  // first commune: the same file (sha256) at each address
  let at = $derived(commune ?? doc.communes[0]?.bfs_id);
  const open = (page?: number) => originalLink(doc.original_url, at, page);
  let named = $derived(commune === undefined || doc.communes.length > 1);
</script>

<article class="document-row">
  <div class="document-date">{dated}</div>
  <div>
    <p class="document-meta">
      {meta}{#if languages.length}<span class="document-languages" aria-label={t.languagesLabel}
          >{#each languages as code}<span class="language" title={label(lang, 'language', code)}
              >{code === 'other' ? label(lang, 'language', code) : code.toUpperCase()}</span
            >{/each}</span
        >{/if}
    </p>
    <h2>{title}</h2>
    {#if doc.sections.length > 1 && contains}<p class="contains">{t.contains} {contains}</p>{/if}
    {#each matches as s}<p class="match family-{s.family}">
        <strong>{name(s)}</strong> · {range(s)} ·
        <a href={open(s.first_page)} target="_blank" rel="noreferrer"
          >{t.openAt.replace('{n}', fmt(s.first_page, lang))} ↗</a
        >
      </p>{/each}
    {#if doc.sections.length > 1 && total > 0}<div class="strip" aria-hidden="true">
        {#each doc.sections as s}<a
            class="segment family-{s.family}"
            class:unseen={s.partly_unseen}
            href={open(s.first_page)}
            target="_blank"
            rel="noreferrer"
            tabindex="-1"
            title={tip(s)}
            aria-label={tip(s)}
            style:left="{(100 * (s.first_page - 1)) / total}%"
            style:width="{(100 * pagesOf(s)) / total}%"
          ></a>{/each}
      </div>{/if}
    {#if doc.sections.length}<ul class="sections" aria-label={t.sections}>
        {#each doc.sections as s}<li>
            <a
              class="family-{s.family}"
              href={open(s.first_page)}
              target="_blank"
              rel="noreferrer"
              title={label(lang, 'family', s.family)}
              ><i class="swatch" aria-hidden="true"></i>{name(s)}
              {range(s)}{#if s.partly_unseen}<span class="unseen-mark" title={t.partlyUnseenTip}
                  >*<span class="sr-only">{t.partlyUnseen}</span></span
                >{/if}</a
            >
          </li>{/each}
      </ul>{/if}
    {#if unseen}<p class="unseen-note" title={t.partlyUnseenTip}>
        * {t.partlyUnseen}<span class="sr-only">. {t.partlyUnseenTip}</span>
      </p>{/if}
    {#if named && doc.communes.length}<p class="communes">
        {doc.communes.length > 1 ? t.communes : t.commune}:
        {#each doc.communes as c, i}{i ? ', ' : ''}<a href={href(`/gemeinden/${c.bfs_id}`, lang)}
            >{c.name}</a
          >
          <small>{c.canton}</small>{/each}
      </p>{/if}
    {#if doc.original_url}<a class="text-link" href={open()} target="_blank" rel="noreferrer"
        >{t.original} ↗</a
      >{/if}
    {#if doc.run_id}<a
        class="run-link"
        href={`${href('/ueber-uns', lang)}#run-${encodeURIComponent(doc.run_id)}`}>{t.runLink}</a
      >{/if}
    <ReportProblem {lang} entry={doc.sha256} source={open()} />
  </div>
  <span class="file-mark" aria-hidden="true">PDF</span>
</article>

<style>
  .document-row {
    border-top: var(--rule);
    padding: var(--space-2xl) 0;
    display: grid;
    grid-template-columns: var(--date-width) minmax(0, 1fr) var(--file-mark-width);
    gap: var(--space-2xl);
  }
  .document-date {
    font-size: var(--font-size-sm);
    color: var(--muted);
    line-height: var(--line-height-loose);
  }
  .document-meta {
    font-size: var(--font-size-xs);
    text-transform: uppercase;
    letter-spacing: var(--letter-spacing-wider);
    color: var(--muted);
  }
  .document-languages {
    margin-left: var(--space-2xs);
  }
  .language {
    display: inline-block;
    border: var(--rule);
    padding: 0 var(--space-2xs);
    margin-left: var(--space-2xs);
    color: var(--ink);
    cursor: help;
  }
  h2 {
    font-size: var(--font-size-xl);
    font-weight: var(--weight-book);
    line-height: var(--line-height-normal);
    margin: var(--space-sm) 0 var(--space-md);
    letter-spacing: var(--letter-spacing-snug);
    overflow-wrap: anywhere;
  }
  .contains {
    font-size: var(--font-size-md);
    margin-bottom: var(--space-sm);
  }
  .match {
    font-size: var(--font-size-md);
    background: var(--band);
    border-left: var(--marker-width) solid var(--family);
    padding: var(--space-sm) var(--space-md);
    margin-bottom: var(--space-sm);
  }
  .match strong {
    font-weight: var(--weight-semibold);
  }
  .match a {
    text-decoration: underline;
    text-underline-offset: var(--underline-offset);
  }
  .match a:hover {
    color: var(--accent);
  }
  .strip {
    position: relative;
    height: var(--strip-height);
    background: var(--band);
    margin: var(--space-sm) 0 var(--space-md);
  }
  .segment {
    position: absolute;
    top: 0;
    bottom: 0;
    background-color: var(--family);
    border-right: var(--space-3xs) solid var(--paper);
  }
  .segment.unseen {
    background-image: var(--hatch-unseen);
  }
  .segment:hover {
    background-color: var(--ink);
  }
  .sections {
    list-style: none;
    display: flex;
    flex-wrap: wrap;
    gap: var(--space-xs);
    padding: 0;
    margin: 0 0 var(--space-md);
  }
  .sections a {
    display: inline-flex;
    align-items: center;
    gap: var(--space-xs);
    font-size: var(--font-size-sm);
    line-height: var(--line-height-normal);
    border: var(--rule);
    padding: var(--space-2xs) var(--space-sm);
    color: var(--ink);
  }
  .sections a:hover {
    border-color: var(--ink);
  }
  .swatch {
    width: var(--legend-key);
    height: var(--legend-key);
    background: var(--family);
  }
  .unseen-mark {
    color: var(--accent);
    cursor: help;
  }
  .unseen-note,
  .communes {
    font-size: var(--font-size-sm);
    line-height: var(--line-height-relaxed);
    color: var(--muted);
    margin-bottom: var(--space-md);
  }
  .unseen-note {
    cursor: help;
  }
  .communes a {
    color: var(--ink);
    text-decoration: underline;
    text-underline-offset: var(--underline-offset);
  }
  .communes small {
    margin-left: var(--space-3xs);
  }
  .run-link,
  .document-row :global(.report-action) {
    margin-left: var(--space-lg);
  }
  .run-link {
    font-size: var(--font-size-sm);
    color: var(--muted);
    text-decoration: underline;
    text-underline-offset: var(--underline-offset);
  }
  .run-link:hover {
    color: var(--accent);
  }
  .file-mark {
    font-size: var(--font-size-2xs);
    border: var(--line-width) solid var(--line-mid);
    width: var(--file-mark-width);
    height: var(--file-mark-height);
    display: grid;
    place-items: center;
    color: var(--faint);
  }
  @media (max-width: 900px) {
    .document-row {
      grid-template-columns: var(--date-width) minmax(0, 1fr);
      gap: var(--space-lg);
    }
    .file-mark {
      display: none;
    }
  }
  @media (max-width: 600px) {
    .document-row {
      grid-template-columns: minmax(0, 1fr);
      gap: var(--space-sm);
      padding: var(--space-xl) 0;
    }
  }
</style>
