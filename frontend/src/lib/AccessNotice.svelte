<script lang="ts">
  import { copy, when, type Lang } from './i18n';
  import type { Access } from './types';
  let { access, lang }: { access: Access[]; lang: Lang } = $props();
  let t = $derived(copy[lang]);
  let restricted = $derived(access.some((a) => a.status === 'restricted' && !a.stale));
</script>

{#if access.length}
  <aside class="access-notice" aria-label={restricted ? t.accessRestricted : t.accessTemporary}>
    <p>
      {restricted
        ? t.accessNotice
        : access.some((a) => a.restricted_at)
          ? t.accessEarlier
          : t.accessTemporary}
    </p>
    <details>
      <summary>{t.accessChecked}: {when(access[0].checked_at, lang)}</summary>
      <ul>
        {#each access as a}
          <li>
            {#if a.status === 'rate_limited'}<p>
                {t.accessRate}
              </p>{:else if a.status === 'robots_unavailable'}<p>{t.accessUnavailable}</p>{/if}
            {#if a.restricted_at && a.status !== 'restricted'}<p>{t.accessEarlier}</p>{/if}
            {#if a.stale}<p>{t.accessStale}</p>{/if}
            <a href={a.source_url} target="_blank" rel="noreferrer">{t.accessSource} ↗</a>
            · <a href={a.robots_url} target="_blank" rel="noreferrer">robots.txt ↗</a>
            · {t.accessChecked}: {when(a.checked_at, lang)}
          </li>
        {/each}
      </ul>
    </details>
  </aside>
{/if}
