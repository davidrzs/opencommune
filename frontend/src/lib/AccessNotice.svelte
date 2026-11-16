<script lang="ts">
  import Info from '@lucide/svelte/icons/info';
  import { copy, when, type Lang } from './i18n';
  import type { Access } from './types';
  let { access, lang }: { access: Access[]; lang: Lang } = $props();
  let t = $derived(copy[lang]);
  let restricted = $derived(access.some((a) => a.status === 'restricted' && !a.stale));
  const link =
    'rounded-sm text-foreground underline decoration-border underline-offset-4 outline-none hover:decoration-foreground focus-visible:ring-2 focus-visible:ring-ring';
</script>

{#if access.length}
  <aside
    class="access-notice mt-6 flex max-w-3xl gap-3 rounded-lg border border-border bg-muted/40 px-4 py-3 text-sm"
    aria-label={restricted ? t.accessRestricted : t.accessTemporary}
  >
    <Info class="mt-0.5 size-4 shrink-0 text-muted-foreground" aria-hidden="true" />
    <div class="min-w-0">
      <p>
        {restricted
          ? t.accessNotice
          : access.some((a) => a.restricted_at)
            ? t.accessEarlier
            : t.accessTemporary}
      </p>
      <details class="mt-1">
        <summary
          class="w-fit cursor-pointer rounded-sm text-muted-foreground outline-none hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring"
          >{t.accessChecked}: {when(access[0].checked_at, lang)}</summary
        >
        <ul class="mt-2 space-y-2 text-muted-foreground">
          {#each access as a}
            <li>
              {#if a.status === 'rate_limited'}<p>
                  {t.accessRate}
                </p>{:else if a.status === 'robots_unavailable'}<p>{t.accessUnavailable}</p>{/if}
              {#if a.restricted_at && a.status !== 'restricted'}<p>{t.accessEarlier}</p>{/if}
              {#if a.stale}<p>{t.accessStale}</p>{/if}
              <p>
                <a class={link} href={a.source_url} target="_blank" rel="noreferrer"
                  >{t.accessSource} ↗</a
                >
                ·
                <a class={link} href={a.robots_url} target="_blank" rel="noreferrer">robots.txt ↗</a
                >
                · {t.accessChecked}: {when(a.checked_at, lang)}
              </p>
            </li>
          {/each}
        </ul>
      </details>
    </div>
  </aside>
{/if}
