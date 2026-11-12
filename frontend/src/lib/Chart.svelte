<script lang="ts">
  // Line or bar chart in the site's style: slate data, the accent for a second series, hairline
  // grid, a hover value on every mark (SVG title), one y axis with its unit.
  type Series = { label: string; values: (number | null)[]; accent?: boolean };
  let {
    kind = 'line',
    labels,
    series,
    unit = '',
    yTitle = '',
    min = undefined,
    max = undefined,
    format = (v: number) => String(v),
    width = 640
  }: {
    kind?: 'line' | 'bar';
    labels: string[];
    series: Series[];
    unit?: string;
    yTitle?: string;
    min?: number;
    max?: number;
    format?: (v: number) => string;
    width?: number;
  } = $props();

  let W = $derived(width);
  let H = $derived(Math.round(width * 0.4));
  const L = 64,
    R = 96,
    T = 14,
    B = 30;
  let pw = $derived(W - L - R);
  let ph = $derived(H - T - B);

  function ticks(lo: number, hi: number) {
    const span = hi - lo || Math.abs(hi) || 1;
    const raw = span / 4;
    const base = 10 ** Math.floor(Math.log10(raw));
    const step = [1, 2, 2.5, 5, 10].map((m) => m * base).find((s) => s >= raw) ?? base * 10;
    const start = Math.floor(lo / step) * step;
    let end = Math.ceil(hi / step) * step;
    if (end <= start) end = start + step;
    const out: number[] = [];
    for (let v = start; v <= end + step / 2; v += step) out.push(Math.round(v * 1e9) / 1e9);
    return out;
  }
  let values = $derived(series.flatMap((s) => s.values).filter((v): v is number => v !== null));
  let grid = $derived(
    ticks(min ?? Math.min(0, ...values), max ?? Math.max(kind === 'bar' ? 0 : -Infinity, ...values))
  );
  let lo = $derived(grid[0]);
  let hi = $derived(grid[grid.length - 1]);
  const x = (i: number) =>
    kind === 'bar'
      ? L + (pw / labels.length) * (i + 0.5)
      : L + (labels.length > 1 ? (pw * i) / (labels.length - 1) : pw / 2);
  const y = (v: number) => T + (ph * (hi - v)) / (hi - lo || 1);
  const every = $derived(Math.max(1, Math.ceil(labels.length / 10)));
</script>

<svg viewBox="0 0 {W} {H}" role="img" class="chart" aria-label={yTitle}>
  {#each grid as v}<line class="grid" x1={L} x2={W - R} y1={y(v)} y2={y(v)} /><text
      class="tick"
      x={L - 8}
      y={y(v) + 4}
      text-anchor="end">{format(v)}</text
    >{/each}
  {#if lo < 0 && hi > 0}<line class="zero" x1={L} x2={W - R} y1={y(0)} y2={y(0)} />{/if}
  {#each labels as label, i}{#if i % every === 0}<text
        class="tick"
        x={x(i)}
        y={H - 8}
        text-anchor="middle">{label}</text
      >{/if}{/each}
  {#if yTitle}<text
      class="tick"
      transform="rotate(-90)"
      x={-(T + ph / 2)}
      y="14"
      text-anchor="middle">{yTitle}</text
    >{/if}
  {#if kind === 'bar'}
    {#each series[0].values as v, i}{#if v !== null}<rect
          class="bar"
          x={x(i) - (pw / labels.length) * 0.32}
          width={(pw / labels.length) * 0.64}
          y={Math.min(y(v), y(0))}
          height={Math.abs(y(v) - y(0))}><title>{labels[i]}: {format(v)}{unit}</title></rect
        >{/if}{/each}
  {:else}
    {#each series as s}
      <polyline
        class="line"
        class:accent={s.accent}
        points={s.values
          .map((v, i) => (v === null ? null : `${x(i)},${y(v)}`))
          .filter(Boolean)
          .join(' ')}
      />
      {#each s.values as v, i}{#if v !== null}<circle
            class="dot"
            class:accent={s.accent}
            cx={x(i)}
            cy={y(v)}
            r="4.5"><title>{s.label} {labels[i]}: {format(v)}{unit}</title></circle
          >{/if}{/each}
      {@const last = s.values.findLastIndex((v) => v !== null)}
      {#if last >= 0}<text class="series-label" x={x(last) + 10} y={y(s.values[last]!) + 4}
          >{s.label}</text
        >{/if}
    {/each}
  {/if}
</svg>

<style>
  .chart {
    width: 100%;
    height: auto;
    display: block;
    font-family: 'DM Sans', sans-serif;
  }
  .grid {
    stroke: var(--line);
    stroke-width: 1;
  }
  .zero {
    stroke: var(--ink);
    stroke-width: 1;
  }
  .tick {
    fill: var(--muted);
    font-size: 12px;
  }
  .series-label {
    fill: var(--ink);
    font-size: 12.5px;
    font-weight: 550;
  }
  .line {
    fill: none;
    stroke: #3a3f47;
    stroke-width: 2;
  }
  .line.accent {
    stroke: var(--accent);
  }
  .dot {
    fill: #3a3f47;
    stroke: #fff;
    stroke-width: 2;
  }
  .dot.accent {
    fill: var(--accent);
  }
  .bar {
    fill: #3a3f47;
  }
  .bar:hover,
  .dot:hover {
    fill: var(--accent);
  }
</style>
