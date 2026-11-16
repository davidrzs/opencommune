<script lang="ts">
  import { goto } from '$app/navigation';
  import { page } from '$app/state';
  import { commune as texts, count } from './copy/commune';
  import type { Filters } from './documents';
  import { copy, fmt, label, type Lang } from './i18n';
  import type { Facet, Family, Holding } from './types';
  // A commune's holdings as a column per year, stacked by section family. Pages: the pages of
  // each family's sections; documents: each document under its first section, so a column adds
  // up to the year's total. A server without those counts sends only the documents per family,
  // which overlap: the chart then shows the yearly totals of the list's year facet (`years`) as
  // one series. A column filters the list by its year, a segment by year and family; the page then
  // moves to the list's heading (`list`, its id).
  let {
    holdings,
    years,
    filters,
    lang,
    list
  }: {
    holdings: Holding[];
    years: Facet[] | null;
    filters: Filters;
    lang: Lang;
    list: string;
  } = $props();
  let t = $derived(copy[lang]);
  let k = $derived(texts[lang]);

  // bottom to top, and the legend's order
  const ORDER: Family[] = ['deliberation', 'proposals', 'information', 'money', 'rules', 'other'];
  // the chart starts here; earlier years are summed in a note
  const FROM = 2007;
  type Mode = 'pages' | 'documents';
  type Year = { year: number; total: number; documents: number; parts: Record<string, number> };

  let detailed = $derived(
    holdings.length > 0 &&
      holdings.every((h) => h.pages !== undefined && h.first_part_documents !== undefined)
  );
  let choice = $state<Mode>('pages');
  let mode = $derived<Mode>(detailed ? choice : 'documents');

  let byYear = $derived.by(() => {
    const rows = new Map<number, Year>();
    const row = (year: number) => {
      if (!rows.has(year)) rows.set(year, { year, total: 0, documents: 0, parts: {} });
      return rows.get(year)!;
    };
    if (detailed)
      for (const h of holdings) {
        const r = row(h.year);
        const n = (mode === 'pages' ? h.pages : h.first_part_documents) ?? 0;
        r.parts[h.family] = (r.parts[h.family] ?? 0) + n;
        r.total += n;
        r.documents += h.first_part_documents ?? 0;
      }
    else
      for (const f of years ?? [])
        if (typeof f.value === 'number') {
          const r = row(f.value);
          r.total = r.documents = f.count;
        }
    return rows;
  });
  // every year from FROM to next year, gaps as empty columns; the years before and after (a
  // misread date, a plan for 2040) are summed
  let span = $derived.by(() => {
    const all = [...byYear.keys()];
    if (!all.length) return null;
    const first = Math.min(...all);
    const last = Math.max(...all);
    const next = new Date().getFullYear() + 1;
    const to = first <= next ? Math.min(last, next) : last;
    const from = to >= FROM ? Math.max(FROM, first) : first;
    const rows: Year[] = [];
    for (let y = from; y <= to; y++)
      rows.push(byYear.get(y) ?? { year: y, total: 0, documents: 0, parts: {} });
    const sum = (years: number[]) => {
      const total: Year = { year: 0, total: 0, documents: 0, parts: {} };
      for (const y of years) {
        const r = byYear.get(y)!;
        total.total += r.total;
        total.documents += r.documents;
        for (const [f, n] of Object.entries(r.parts)) total.parts[f] = (total.parts[f] ?? 0) + n;
      }
      return total;
    };
    const older = sum(all.filter((y) => y < from));
    const later = sum(all.filter((y) => y > to));
    return { from, to, rows, older, later };
  });
  // the families with something to show, in ORDER
  let families = $derived(
    detailed ? ORDER.filter((f) => [...byYear.values()].some((r) => r.parts[f])) : []
  );

  const unit = (n: number) => count(n, mode === 'pages' ? 'page' : 'document', lang);
  const familyName = (f: string) => label(lang, 'family', f);
  function summary(r: Year) {
    const parts = families
      .filter((f) => r.parts[f])
      .map((f) => `${familyName(f)} ${fmt(r.parts[f], lang)}`);
    return `${r.year}: ${unit(r.total)}${parts.length ? `; ${parts.join(', ')}` : ''}`;
  }

  // geometry, in pixels of the measured width
  let width = $state(0);
  const T = 8;
  const B = 24;
  const R = 8;
  const GAP = 2;
  let height = $derived(width < 640 ? 200 : 240);
  let top = $derived.by(() => {
    const max = Math.max(0, ...(span?.rows ?? []).map((r) => r.total));
    if (max <= 1) return 1;
    const step = 10 ** Math.floor(Math.log10(max));
    return [1, 1.5, 2, 2.5, 3, 4, 5, 6, 8, 10].map((m) => m * step).find((v) => v >= max)!;
  });
  let ticks = $derived(Number.isInteger(top / 2) ? [0, top / 2, top] : [0, top]);
  let L = $derived(10 + 6.5 * fmt(top, lang).length);
  let n = $derived(span?.rows.length ?? 0);
  let step = $derived(n ? (width - L - R) / n : 0);
  let bar = $derived(Math.min(32, Math.max(2, step - Math.max(2, step * 0.3))));
  const y = (v: number) => T + (height - T - B) * (1 - v / top);
  // a year label every few columns, counted from the newest, which always has one
  let every = $derived(Math.max(1, Math.ceil(n / Math.max(1, Math.floor((width - L) / 56)))));
  const x = (i: number) => L + i * step + (step - bar) / 2;
  // a stack's segments; a 2 px white gap above each but the top one, whose corners are rounded
  function segments(r: Year) {
    const parts: [string | null, number][] = detailed
      ? ORDER.filter((f) => r.parts[f]).map((f) => [f, r.parts[f]])
      : r.total
        ? [[null, r.total]]
        : [];
    let base = 0;
    return parts.map(([family, v], j) => {
      const y1 = y(base);
      const y2 = y(base + v);
      base += v;
      const last = j === parts.length - 1;
      return {
        family,
        last,
        top: last ? y2 : y2 + GAP,
        height: Math.max(0, last ? y1 - y2 : y1 - y2 - GAP)
      };
    });
  }
  function rounded(left: number, top: number, w: number, h: number) {
    const r = Math.min(4, w / 2, h);
    const bottom = top + h;
    return `M${left},${bottom}V${top + r}Q${left},${top} ${left + r},${top}H${left + w - r}Q${left + w},${top} ${left + w},${top + r}V${bottom}Z`;
  }
  const fill = (family: string | null) => (family ? `var(--family-${family})` : 'var(--primary)');
  // the list's filters, shown on the chart: the other years and families recede
  let picked = $derived(filters.family || filters.first_family);
  const chosen = (year: number, family: string | null) =>
    (!filters.year || filters.year === String(year)) && (!picked || !family || picked === family);
  let filtering = $derived(Boolean(filters.year || (detailed && picked)));

  // the list filtered by a year and a family; other filters go. Pages: the documents with a
  // section of the family; documents: those whose first section is of it, as the column counts
  // them, so the list holds as many documents as the segment says.
  const link = (year: number, family?: string | null) => {
    const key = mode === 'documents' && detailed ? 'first_family' : 'family';
    return `${page.url.pathname}?year=${year}${family ? `&${key}=${family}` : ''}`;
  };
  function follow(event: MouseEvent, url: string) {
    if (event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey)
      return;
    event.preventDefault();
    goto(url, { noScroll: true, keepFocus: true }).then(() => {
      const heading = document.getElementById(list);
      if (!heading) return;
      heading.focus({ preventScroll: true });
      const still = matchMedia('(prefers-reduced-motion: reduce)').matches;
      heading.scrollIntoView({ behavior: still ? 'auto' : 'smooth', block: 'start' });
    });
  }
  function choose(event: MouseEvent, year: number) {
    const family = (event.target as Element).closest('[data-family]')?.getAttribute('data-family');
    follow(event, link(year, family));
  }

  // one tab stop: the arrow keys move between the years
  let svg = $state<SVGSVGElement>();
  let current = $state<number | null>(null);
  let tabbable = $derived.by(() => {
    if (current !== null && current < n) return current;
    const i = span?.rows.findIndex((r) => String(r.year) === filters.year) ?? -1;
    return i >= 0 ? i : n - 1;
  });
  function keys(event: KeyboardEvent, i: number) {
    const next =
      event.key === 'ArrowRight'
        ? Math.min(n - 1, i + 1)
        : event.key === 'ArrowLeft'
          ? Math.max(0, i - 1)
          : event.key === 'Home'
            ? 0
            : event.key === 'End'
              ? n - 1
              : null;
    if (next === null) return;
    event.preventDefault();
    current = next;
    svg?.querySelectorAll<SVGAElement>('a.column')[next]?.focus();
  }

  // the tooltip of the column under the pointer or in focus, beside it where there is room
  let shown = $state<number | null>(null);
  const TIP = 256;
  let tip = $derived.by(() => {
    if (shown === null || !span || shown >= n) return null;
    const left = L + shown * step;
    const place =
      left + step + 8 + TIP <= width
        ? left + step + 8
        : left - 8 - TIP >= 0
          ? left - 8 - TIP
          : Math.max(0, Math.min(width - TIP, left + step / 2 - TIP / 2));
    return { row: span.rows[shown], left: place };
  });
</script>

<!-- a table row of the years left out of the chart: "vor 2007", "nach 2027" -->
{#if span}
  <section class="holdings mt-12 border-t border-border pt-8" aria-labelledby="holdings-title">
    <div class="flex flex-wrap items-baseline justify-between gap-x-6 gap-y-1">
      <h2 id="holdings-title" class="text-xl font-semibold tracking-tight">
        {mode === 'pages' ? k.pagesPerYear : k.documentsPerYear}
      </h2>
      {#if span.older.total || span.later.total}<p class="text-sm text-muted-foreground">
          {[
            span.older.total &&
              k.older
                .replace('{count}', unit(span.older.total))
                .replace('{year}', String(span.from)),
            span.later.total &&
              k.later.replace('{count}', unit(span.later.total)).replace('{year}', String(span.to))
          ]
            .filter(Boolean)
            .join(' · ')}
        </p>{/if}
    </div>
    {#if detailed}<div class="mt-4 flex flex-wrap items-center justify-between gap-3">
        <div
          class="inline-flex rounded-lg border border-border p-0.5 text-sm"
          role="group"
          aria-label={k.view}
        >
          {#each ['pages', 'documents'] as const as m}<button
              type="button"
              aria-pressed={mode === m}
              onclick={() => (choice = m)}
              class="rounded-md px-3 py-1 outline-none focus-visible:ring-2 focus-visible:ring-ring {mode ===
              m
                ? 'bg-foreground text-background'
                : 'text-muted-foreground hover:text-foreground'}"
              >{m === 'pages' ? k.pages : k.documents}</button
            >{/each}
        </div>
        <ul class="flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted-foreground">
          {#each families as f}<li class="inline-flex items-center gap-1.5">
              <span class="size-2.5 rounded-sm" style:background={fill(f)} aria-hidden="true"
              ></span>{familyName(f)}
            </li>{/each}
        </ul>
      </div>{/if}
    <div
      class="relative mt-4"
      bind:clientWidth={width}
      onpointerleave={() => (shown = null)}
      role="group"
      aria-label={k.chartLabel
        .replace('{title}', mode === 'pages' ? k.pagesPerYear : k.documentsPerYear)
        .replace('{from}', String(span.from))
        .replace('{to}', String(span.to))}
    >
      {#if width > 0}<svg
          bind:this={svg}
          {width}
          {height}
          viewBox="0 0 {width} {height}"
          class="block select-none"
          font-size="11"
        >
          {#each ticks as v}<line
              x1={L}
              x2={width - R}
              y1={y(v)}
              y2={y(v)}
              class="stroke-border"
              stroke-width="1"
            /><text x={L - 8} y={y(v) + 4} text-anchor="end" class="fill-muted-foreground"
              >{fmt(v, lang)}</text
            >{/each}
          {#each span.rows as r, i (r.year)}<a
              class="column"
              href={link(r.year)}
              tabindex={i === tabbable ? 0 : -1}
              aria-label={summary(r)}
              onclick={(event) => choose(event, r.year)}
              onkeydown={(event) => keys(event, i)}
              onfocus={() => ((shown = i), (current = i))}
              onblur={() => (shown = null)}
              onpointerenter={() => (shown = i)}
              ><rect
                class="hit"
                x={L + i * step}
                y={T}
                width={step}
                height={height - T - B}
                rx="4"
              />
              <g class="marks">
                {#each segments(r) as s}{#if s.last}<path
                      d={rounded(x(i), s.top, bar, s.height)}
                      style:fill={fill(s.family)}
                      data-family={s.family}
                      class:recede={filtering && !chosen(r.year, s.family)}
                    />{:else}<rect
                      x={x(i)}
                      y={s.top}
                      width={bar}
                      height={s.height}
                      style:fill={fill(s.family)}
                      data-family={s.family}
                      class:recede={filtering && !chosen(r.year, s.family)}
                    />{/if}{/each}
              </g>
              {#if (n - 1 - i) % every === 0}<text
                  x={x(i) + bar / 2}
                  y={height - 6}
                  text-anchor="middle"
                  class={filters.year === String(r.year)
                    ? 'fill-foreground font-semibold'
                    : 'fill-muted-foreground'}>{r.year}</text
                >{/if}</a
            >{/each}
        </svg>{/if}
      {#if tip}<div
          class="pointer-events-none absolute top-0 z-10 rounded-lg border border-border bg-popover p-3 text-xs text-popover-foreground shadow-md"
          style:left="{tip.left}px"
          style:width="{TIP}px"
          aria-hidden="true"
        >
          <div class="flex items-baseline justify-between gap-3 font-semibold">
            <span>{tip.row.year}</span>
            <span class="tabular-nums">{unit(tip.row.total)}</span>
          </div>
          {#if mode === 'pages' && tip.row.documents}<p
              class="text-right text-muted-foreground tabular-nums"
            >
              {count(tip.row.documents, 'document', lang)}
            </p>{/if}
          {#if detailed && tip.row.total}<ul class="mt-2 space-y-1">
              {#each families as f}{#if tip.row.parts[f]}<li
                    class="flex items-center justify-between gap-3"
                  >
                    <span
                      class="inline-flex items-center gap-1.5 whitespace-nowrap text-muted-foreground"
                      ><span class="h-1 w-3 rounded-full" style:background={fill(f)}
                      ></span>{familyName(f)}</span
                    ><span class="font-medium tabular-nums">{fmt(tip.row.parts[f], lang)}</span>
                  </li>{/if}{/each}
            </ul>
            <p class="mt-2 text-muted-foreground">
              {mode === 'pages' ? k.pagesNote : k.documentsNote}
            </p>{/if}
          {#if tip.row.total}<p class="mt-1 text-muted-foreground">{k.clickHint}</p>{/if}
        </div>{/if}
    </div>
  </section>
{/if}

<style>
  .column {
    cursor: pointer;
    outline: none;
  }
  .hit {
    fill: transparent;
  }
  .column:focus-visible .hit {
    stroke: var(--ring);
    stroke-width: 2;
  }
  .column:hover .marks,
  .column:focus-visible .marks {
    opacity: 0.82;
  }
  .recede {
    opacity: 0.3;
  }
</style>
