<script lang="ts">
  // The commune map. Full: every commune of `communes` as a link, shaded in five steps by its
  // number of documents. Compact (the commune page): the region around `communes`, which are shown
  // in the brand red.
  import { copy, fmt, href, type Lang } from '$lib/i18n';
  import { docs, start } from '$lib/copy/start';
  import { page } from '$app/state';
  import map from './ch-map.json';
  import { type Commune, hasDocuments, restricted } from './types';
  let { communes, compact = false }: { communes: Commune[]; compact?: boolean } = $props();
  let lang = $derived((page.params.lang || 'de') as Lang);
  let t = $derived(copy[lang]);
  let s = $derived(start[lang]);
  const patternId = $props.id();
  const shapes = map.municipalities as Record<string, string>;
  const { width: W, height: H } = map.projection;

  // Five steps by quantiles of the communes' document counts: a step starts at the count of the
  // commune at 20, 40, 60 and 80 per cent of the communes with documents.
  let counts = $derived(
    communes
      .filter(hasDocuments)
      .map((c) => c.documents)
      .sort((a, b) => a - b)
  );
  let breaks = $derived(
    [...new Set([1, 2, 3, 4].map((i) => counts[Math.floor((counts.length * i) / 5)]))].filter(
      (b) => b > counts[0]
    )
  );
  const level = (n: number) => (n > 0 ? 1 + breaks.filter((b) => n >= b).length : 0);
  // the legend: each step's range of counts
  let steps = $derived(
    counts.length
      ? [counts[0], ...breaks].map((from, i) => {
          const to = i < breaks.length ? breaks[i] - 1 : counts[counts.length - 1];
          return {
            level: i + 1,
            label: from === to ? fmt(from, lang) : `${fmt(from, lang)}–${fmt(to, lang)}`
          };
        })
      : []
  );

  const summary = (c: Commune) => (c.documents ? docs(c.documents, lang) : s.noDocuments);
  const label = (c: Commune) =>
    `${c.name}, ${c.canton}: ${summary(c)}.${restricted(c) ? ` ${t.accessRestricted}.` : ''}`;
  let byId = $derived(Object.fromEntries(communes.map((c) => [c.bfs_id, c])));

  // numbers of a path: x, y, x, y, ...
  const coordinates = (d: string) => d.match(/-?\d+(?:\.\d+)?/g)!.map(Number);
  function location(c: Commune): [number, number] | null {
    if (c.lat != null && c.lon != null) {
      const p = map.projection;
      return [(c.lon - p.lon0) * p.cos * p.k, (p.lat1 - c.lat) * p.k];
    }
    return null;
  }
  // compact: a 3:2 window around the communes, at least 150 map units wide, inside the map
  let view = $derived.by(() => {
    if (!compact) return `0 0 ${W} ${H}`;
    const xs: number[] = [];
    const ys: number[] = [];
    for (const c of communes) {
      const d = shapes[String(c.bfs_id)];
      const nums = d ? coordinates(d) : (location(c) ?? []);
      for (let i = 0; i + 1 < nums.length; i += 2) {
        xs.push(nums[i]);
        ys.push(nums[i + 1]);
      }
    }
    if (!xs.length) return `0 0 ${W} ${H}`;
    const [x0, x1, y0, y1] = [Math.min(...xs), Math.max(...xs), Math.min(...ys), Math.max(...ys)];
    let w = Math.max(150, (x1 - x0) * 1.8, (y1 - y0) * 1.8 * 1.5);
    w = Math.min(w, W);
    const h = Math.min((w * 2) / 3, H);
    const x = Math.min(Math.max((x0 + x1) / 2 - w / 2, 0), W - w);
    const y = Math.min(Math.max((y0 + y1) / 2 - h / 2, 0), H - h);
    return `${x.toFixed(1)} ${y.toFixed(1)} ${w.toFixed(1)} ${h.toFixed(1)}`;
  });
  // compact: the other communes, drawn without links
  let around = $derived(
    compact
      ? Object.entries(shapes)
          .filter(([id]) => !byId[Number(id)])
          .map(([, d]) => d)
      : []
  );

  // the tooltip: the commune under the pointer
  let box: HTMLDivElement;
  let hovered = $state<Commune | null>(null);
  let tip = $state({ x: 0, y: 0, left: false });
  function under(e: Event) {
    const a = (e.target as Element).closest?.('a[data-bfs]');
    return a ? (byId[Number(a.getAttribute('data-bfs'))] ?? null) : null;
  }
  function place(x: number, y: number) {
    const r = box.getBoundingClientRect();
    tip = { x: x - r.left, y: y - r.top, left: x - r.left > r.width / 2 };
  }
  function pointermove(e: PointerEvent) {
    if (compact || e.pointerType === 'touch') return;
    hovered = under(e);
    if (hovered) place(e.clientX, e.clientY);
  }
</script>

<div
  bind:this={box}
  class={[
    'atlas-map relative',
    compact && 'compact overflow-hidden rounded-xl border border-border bg-white'
  ]}
>
  <!-- A picture for screen readers and outside the tab order: the commune finder and the list
       next to it reach every commune by keyboard, without 2,000 stops on the way. -->
  <svg
    viewBox={view}
    aria-label={compact && communes.length === 1
      ? s.mapPlace.replace('{name}', communes[0].name)
      : t.mapLabel}
    role="img"
    onpointermove={pointermove}
    onpointerleave={() => (hovered = null)}
  >
    <defs
      ><pattern
        id={patternId}
        width="6"
        height="6"
        patternUnits="userSpaceOnUse"
        patternTransform="rotate(35)"
        ><line class="hatch-line" x1="0" y1="0" x2="0" y2="6" /></pattern
      ></defs
    >
    <!-- the land under communes without a row -->
    {#each map.cantons as c}<path class="land" d={c.d} />{/each}
    {#each around as d}<path class="around" {d} />{/each}
    {#each communes as c (c.bfs_id)}
      {@const d = shapes[String(c.bfs_id)]}
      {#if d}<a
          href={href(`/gemeinden/${c.bfs_id}`, lang)}
          tabindex="-1"
          data-bfs={c.bfs_id}
          aria-label={label(c)}
          ><path
            class={[
              'municipality',
              compact ? 'here' : hasDocuments(c) ? 'has-documents' : 'no-documents'
            ]}
            data-level={compact ? undefined : level(c.documents)}
            {d}
          />{#if restricted(c)}<path
              {d}
              fill={`url(#${patternId})`}
              pointer-events="none"
            />{/if}</a
        >{:else if compact}
        {@const point = location(c)}
        {#if point}<circle class="here" cx={point[0]} cy={point[1]} r="4" />{/if}
      {/if}
    {/each}
    {#each map.lakes as d}<path class="lake" {d} />{/each}
    {#each map.cantons as c}<path class="canton" d={c.d} />{/each}
  </svg>

  {#if hovered}
    <div
      class="map-caption pointer-events-none absolute z-10 rounded-md border border-border bg-white px-2 py-1 text-sm whitespace-nowrap shadow-md"
      style:left="{tip.x}px"
      style:top="{tip.y}px"
      style:transform={tip.left ? 'translate(calc(-100% - 12px), 14px)' : 'translate(12px, 14px)'}
      aria-hidden="true"
    >
      <span class="font-medium">{hovered.name}</span>
      <span class="text-muted-foreground">{hovered.canton}</span>
      <span class="text-muted-foreground">· {summary(hovered)}</span>
      {#if restricted(hovered)}<span class="block text-xs text-muted-foreground"
          >{t.accessRestricted}</span
        >{/if}
    </div>
  {/if}
</div>
{#if compact && communes.length === 1}
  <p class="location-caption mt-1 text-xs text-muted-foreground">
    {s.mapNear.replace('{name}', communes[0].name)}
  </p>
{:else if !compact}
  <div
    class="map-legend mt-3 flex flex-wrap items-center gap-x-5 gap-y-2 text-xs text-muted-foreground"
  >
    {#if steps.length}<span class="flex flex-wrap items-center gap-x-3 gap-y-1"
        ><span>{s.mapLegend}</span>{#each steps as step}<span
            class="inline-flex items-center gap-1.5"
            ><span class="key size-3 rounded-sm" data-level={step.level}></span>{step.label}</span
          >{/each}</span
      >{/if}
    <span class="inline-flex items-center gap-1.5"
      ><span class="key size-3 rounded-sm border border-border" data-level="0"
      ></span>{t.missing}</span
    >
    <span class="inline-flex items-center gap-1.5"
      ><svg class="size-3 rounded-sm" aria-hidden="true"
        ><rect class="key-fill" width="100%" height="100%" /><rect
          width="100%"
          height="100%"
          fill={`url(#${patternId})`}
        /></svg
      >{t.accessRestricted}</span
    >
    <span>{t.borders}: © swisstopo / swiss-maps</span>
  </div>
{/if}

<style>
  .atlas-map,
  .map-legend {
    /* the five steps: the brand red mixed with white */
    --map-l1: color-mix(in srgb, var(--brand) 56%, #fff);
    --map-l2: color-mix(in srgb, var(--brand) 66%, #fff);
    --map-l3: color-mix(in srgb, var(--brand) 76%, #fff);
    --map-l4: color-mix(in srgb, var(--brand) 86%, #fff);
    --map-l5: color-mix(in srgb, var(--brand) 96%, #fff);
  }
  .atlas-map > svg {
    display: block;
    width: 100%;
    height: auto;
  }
  .land,
  .around {
    fill: var(--map-none);
  }
  .around,
  .municipality {
    stroke: #fff;
    stroke-width: 0.3;
    stroke-linejoin: round;
  }
  .municipality {
    fill: var(--map-none);
    transition: fill 0.12s;
  }
  .municipality[data-level='1'] {
    fill: var(--map-l1);
  }
  .municipality[data-level='2'] {
    fill: var(--map-l2);
  }
  .municipality[data-level='3'] {
    fill: var(--map-l3);
  }
  .municipality[data-level='4'] {
    fill: var(--map-l4);
  }
  .municipality[data-level='5'] {
    fill: var(--map-l5);
  }
  .lake {
    fill: var(--map-lake);
    pointer-events: none;
  }
  .canton {
    fill: none;
    stroke: #fff;
    stroke-width: 1.1;
    stroke-linejoin: round;
    pointer-events: none;
  }
  .hatch-line {
    stroke: rgb(24 24 27 / 0.4);
    stroke-width: 1;
  }
  a {
    outline: none;
  }
  a:hover > .municipality.has-documents,
  a:focus-visible > .municipality.has-documents {
    fill: color-mix(in srgb, var(--brand), #000 30%);
  }
  a:hover > .municipality.no-documents,
  a:focus-visible > .municipality.no-documents {
    fill: #d4d4d8;
  }
  a:focus-visible > .municipality {
    stroke: var(--foreground);
    stroke-width: 1.2;
  }
  /* compact: strokes in screen pixels, whatever the zoom */
  .compact .around,
  .compact .municipality {
    vector-effect: non-scaling-stroke;
    stroke-width: 0.6;
  }
  .compact .canton {
    vector-effect: non-scaling-stroke;
    stroke-width: 1.6;
  }
  .compact .municipality.here,
  .compact circle.here {
    fill: var(--brand);
  }
  .compact a:hover > .municipality.here,
  .compact a:focus-visible > .municipality.here {
    fill: var(--brand-dark);
  }
  .compact a:focus-visible > .municipality.here {
    stroke: var(--foreground);
    stroke-width: 2;
  }
  .key[data-level='0'] {
    background: var(--map-none);
  }
  .key[data-level='1'] {
    background: var(--map-l1);
  }
  .key[data-level='2'] {
    background: var(--map-l2);
  }
  .key[data-level='3'] {
    background: var(--map-l3);
  }
  .key[data-level='4'] {
    background: var(--map-l4);
  }
  .key[data-level='5'] {
    background: var(--map-l5);
  }
  .key-fill {
    fill: color-mix(in srgb, var(--brand) 66%, #fff);
  }
</style>
