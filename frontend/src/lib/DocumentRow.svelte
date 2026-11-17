<script lang="ts">
  import PageHits from './PageHits.svelte';
  import ReportProblem from './ReportProblem.svelte';
  import { findWords, marked, originalLink } from './documents';
  import { copy, fmt, href, label, when, type Lang } from './i18n';
  import type { Document, PageHit, Section } from './types';
  // `commune`: the commune whose page lists the file; its link to the original is used, and the
  // file's communes are named only when there are several. `section` and `family`: the list's
  // filters; the sections they match get a line of their own. `hits` and `matching`: in a
  // full-text search, the file's best matching pages and how many of its pages match. `q`: the
  // words searched for, marked in the title; `fullText`: read as the full-text search reads them,
  // else as the title search.
  let {
    doc,
    lang,
    commune,
    section = '',
    family = '',
    hits,
    matching = 0,
    q = '',
    fullText = false
  }: {
    doc: Document;
    lang: Lang;
    commune?: number;
    section?: string;
    family?: string;
    hits?: PageHit[];
    matching?: number;
    q?: string;
    fullText?: boolean;
  } = $props();
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
  // the title with the searched words marked
  let titleRuns = $derived(marked(title, findWords(title, q, fullText)));
</script>

<article class="document-row border-b border-border py-5">
  <p class="text-sm leading-6 text-muted-foreground">
    {#if named && doc.communes.length}<span class="communes"
        ><span class="sr-only">{`${doc.communes.length > 1 ? t.communes : t.commune}: `}</span
        >{#each doc.communes as c, i}{i ? ', ' : ''}<a
            class="font-medium text-foreground underline-offset-4 hover:underline"
            href={href(`/gemeinden/${c.bfs_id}`, lang)}>{c.name}</a
          >
          <small class="text-sm">{c.canton}</small>{/each}</span
      >{' · '}{/if}<span class="document-date">{dated}</span
    >{#if meta || languages.length}{' · '}<span class="document-meta"
        >{meta}{#if languages.length}<span class="ml-1.5" aria-label={t.languagesLabel}
            >{#each languages as code}<span
                class="language mr-1 inline-block cursor-help rounded border border-border px-1 text-xs leading-4 font-medium text-zinc-600"
                title={label(lang, 'language', code)}
                >{code === 'other' ? label(lang, 'language', code) : code.toUpperCase()}</span
              >{/each}</span
          >{/if}</span
      >{/if}
  </p>
  <h2 class="mt-1 text-[15px] leading-snug font-medium [overflow-wrap:anywhere] text-foreground">
    {#each titleRuns as run}{#if run.marked}<mark class="rounded-sm bg-primary/10 text-inherit"
          >{run.text}</mark
        >{:else}{run.text}{/if}{/each}
  </h2>
  {#if doc.sections.length > 1 && contains}<p class="contains mt-1 text-sm text-muted-foreground">
      {t.contains}
      {contains}
    </p>{/if}
  {#if hits?.length}<PageHits
      {hits}
      {matching}
      sections={doc.sections}
      languages={doc.languages}
      {lang}
      {at}
    />{/if}
  {#each matches as s}<p
      class="match family-{s.family} mt-2 w-fit max-w-full rounded-md bg-zinc-50 px-3 py-1.5 text-sm"
    >
      <i class="mr-1.5 inline-block size-2 rounded-full bg-(--family)" aria-hidden="true"
      ></i><strong class="font-medium">{name(s)}</strong>
      · {range(s)} ·
      <a
        class="text-primary underline-offset-4 hover:underline"
        href={open(s.first_page)}
        target="_blank"
        rel="nofollow noreferrer">{t.openAt.replace('{n}', fmt(s.first_page, lang))} ↗</a
      >
    </p>{/each}
  {#if doc.sections.length > 1 && total > 0}<div
      class="strip relative mt-3 h-1 max-w-2xl overflow-hidden rounded-full bg-muted"
      aria-hidden="true"
    >
      {#each doc.sections as s}<a
          class="segment family-{s.family} absolute inset-y-0 border-r-2 border-white bg-(--family) hover:opacity-70"
          class:unseen={s.partly_unseen}
          href={open(s.first_page)}
          target="_blank"
          rel="nofollow noreferrer"
          tabindex="-1"
          title={tip(s)}
          aria-label={tip(s)}
          style:left="{(100 * (s.first_page - 1)) / total}%"
          style:width="{(100 * pagesOf(s)) / total}%"
        ></a>{/each}
    </div>{/if}
  {#if doc.sections.length}<ul
      class="sections mt-2.5 flex flex-wrap gap-1.5"
      aria-label={t.sections}
    >
      {#each doc.sections as s}<li>
          <a
            class="family-{s.family} inline-flex items-center gap-1.5 rounded-md border border-border px-2 py-0.5 text-xs text-zinc-700 hover:border-zinc-400 hover:text-foreground"
            href={open(s.first_page)}
            target="_blank"
            rel="nofollow noreferrer"
            title={label(lang, 'family', s.family)}
            ><i class="size-2 shrink-0 rounded-full bg-(--family)" aria-hidden="true"></i>{name(s)}
            <span class="text-muted-foreground">{range(s)}</span>{#if s.partly_unseen}<span
                class="unseen-mark -ml-1 cursor-help text-primary"
                title={t.partlyUnseenTip}>*<span class="sr-only">{t.partlyUnseen}</span></span
              >{/if}</a
          >
        </li>{/each}
    </ul>{/if}
  {#if unseen}<p
      class="unseen-note mt-2 cursor-help text-xs text-muted-foreground"
      title={t.partlyUnseenTip}
    >
      * {t.partlyUnseen}<span class="sr-only">. {t.partlyUnseenTip}</span>
    </p>{/if}
  <div class="links mt-3 flex flex-wrap items-baseline gap-x-5 gap-y-1 text-sm">
    {#if doc.original_url}<a
        class="text-link font-medium text-primary underline-offset-4 hover:underline"
        href={open()}
        target="_blank"
        rel="nofollow noreferrer">{t.original} ↗</a
      >{/if}
    <ReportProblem {lang} entry={doc.sha256} source={open()} />
    {#if doc.run_id}<a
        class="run-link text-muted-foreground hover:text-foreground"
        href={`${href('/ueber-uns', lang)}#run-${encodeURIComponent(doc.run_id)}`}>{t.runLink}</a
      >{/if}
  </div>
</article>

<style>
  /* a section family's colour, by class on chips, strip segments, matching sections and pages */
  .document-row :global(.family-deliberation) {
    --family: var(--family-deliberation);
  }
  .document-row :global(.family-proposals) {
    --family: var(--family-proposals);
  }
  .document-row :global(.family-information) {
    --family: var(--family-information);
  }
  .document-row :global(.family-money) {
    --family: var(--family-money);
  }
  .document-row :global(.family-rules) {
    --family: var(--family-rules);
  }
  .document-row :global(.family-other) {
    --family: var(--family-other);
  }
  /* pages of the section that the classifier did not all see */
  .segment.unseen {
    background-image: repeating-linear-gradient(
      135deg,
      rgb(255 255 255 / 0.65) 0 2px,
      transparent 2px 4px
    );
  }
  .links :global(.report-action) {
    font-size: inherit;
    color: var(--muted-foreground);
  }
  .links :global(.report-action a:hover) {
    color: var(--foreground);
  }
</style>
