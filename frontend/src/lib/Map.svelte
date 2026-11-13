<script lang="ts">
  import { copy, href, fmt, type Lang } from '$lib/i18n';
  import { page } from '$app/state';
  let lang = $derived((page.params.lang || 'de') as Lang);
  let t = $derived(copy[lang]);
  const number = (n: number) => fmt(n, lang);
  import map from './ch-map.json';
  import { type Commune, hasData, hasDocuments } from './types';
  let { communes, compact = false }: { communes: Commune[]; compact?: boolean } = $props();
  let hovered = $state<Commune | null>(null);
  const cantons = [
    'ZH',
    'BE',
    'LU',
    'UR',
    'SZ',
    'OW',
    'NW',
    'GL',
    'ZG',
    'FR',
    'SO',
    'BS',
    'BL',
    'SH',
    'AR',
    'AI',
    'SG',
    'GR',
    'AG',
    'TG',
    'TI',
    'VD',
    'VS',
    'NE',
    'GE',
    'JU'
  ];
  const patternId = $props.id();
  const restricted = (c: Commune) => c.access === 'restricted';
  const accessLabel = (c: Commune) =>
    c.access === 'restricted'
      ? t.accessRestricted
      : c.access === 'earlier'
        ? t.accessEarlier
        : c.access === 'temporary'
          ? t.accessTemporary
          : '';
  const summary = (c: Commune) =>
    [
      c.minutes ? `${number(c.minutes)} ${t.minutesUnit}` : '',
      c.finance_years ? `${number(c.finance_years)} ${t.financeYears}` : '',
      c.decisions ? `${number(c.decisions)} ${t.decisions}` : ''
    ]
      .filter(Boolean)
      .join(' · ');
  const shapes = map.municipalities as Record<string, string>;
  function xy(c: Commune) {
    const p = map.projection;
    return [(c.lon! - p.lon0) * p.cos * p.k, (p.lat1 - c.lat!) * p.k];
  }
  function location(c: Commune) {
    if (c.lat != null && c.lon != null) return xy(c);
    const shape = shapes[String(c.bfs_id)];
    return shape ? center(shape) : null;
  }
  function center(d: string) {
    const nums = d.match(/-?\d+(?:\.\d+)?/g)!.map(Number);
    let x = 0,
      y = 0;
    for (let i = 0; i < nums.length; i += 2) {
      x += nums[i];
      y += nums[i + 1];
    }
    return [x / (nums.length / 2), y / (nums.length / 2)];
  }
</script>

<div class:compact class="atlas-map">
  <svg viewBox={`0 0 ${map.projection.width} ${map.projection.height}`} aria-label={t.mapLabel}>
    <defs
      ><pattern
        id={patternId}
        width="7"
        height="7"
        patternUnits="userSpaceOnUse"
        patternTransform="rotate(35)"
        ><line x1="0" y1="0" x2="0" y2="7" stroke="#596574" stroke-width="1.4" /></pattern
      ></defs
    >
    {#each map.cantons as c}<path class="canton" d={c.d} />{/each}
    {#each map.lakes as d}<path class="lake" {d} />{/each}
    {#each communes as c}<a
        href={href(`/gemeinden/${c.bfs_id}`, lang)}
        aria-label={`${c.name}, ${c.canton}${summary(c) ? `: ${summary(c)}` : ''}. ${accessLabel(c)}`}
        onpointerenter={() => (hovered = c)}
        onpointerleave={() => (hovered = null)}
        onfocus={() => (hovered = c)}
        onblur={() => (hovered = null)}
      >
        {#if shapes[String(c.bfs_id)]}<path
            class="municipality"
            class:has-decisions={hasData(c)}
            class:has-documents={!hasData(c) && hasDocuments(c)}
            class:no-documents={!hasData(c) && !hasDocuments(c)}
            d={shapes[String(c.bfs_id)]}
          />{#if restricted(c)}<path
              d={shapes[String(c.bfs_id)]}
              fill={`url(#${patternId})`}
              pointer-events="none"
            />{/if}{/if}
        {#if hasData(c) && c.lat && c.lon}<circle
            class="municipality-point"
            cx={xy(c)[0]}
            cy={xy(c)[1]}
            r={compact ? 3 : 2.5}
          />{/if}<title>{[c.name, summary(c)].filter(Boolean).join(' · ')}</title>
      </a>{/each}
    {#each map.cantons as c}<text class="canton-name" x={center(c.d)[0]} y={center(c.d)[1]}
        >{cantons[c.id - 1]}</text
      >{/each}
    {#if compact}
      {#each communes as c}
        {@const point = location(c)}
        {#if point}
          <g class="selected-location" aria-hidden="true">
            <circle class="location-halo" cx={point[0]} cy={point[1]} r="25" />
            <circle class="location-dot" cx={point[0]} cy={point[1]} r="11" />
          </g>
        {/if}
      {/each}
    {/if}
  </svg>
  {#if compact && communes.length === 1}
    <p class="location-caption">{communes[0].name} <span>· {communes[0].canton}</span></p>
  {/if}
  {#if !compact}<div class="map-caption" aria-live="polite">
      {#if hovered}<strong>{hovered.name} <small>{hovered.canton}</small></strong><span
          >{accessLabel(hovered)}
          {accessLabel(hovered) ? '·' : ''}
          {summary(hovered)} <span aria-hidden="true">↗</span></span
        >{:else}<span>{t.mapChoose}</span><span aria-hidden="true">↗</span>{/if}
    </div>{/if}
</div>
