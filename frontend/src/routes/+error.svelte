<script lang="ts">
  import { onMount } from 'svelte';
  import { page } from '$app/state';
  import { Button } from '$lib/components/ui/button';
  import { errorPage } from '$lib/copy/pages';
  import { copy, href, type Lang } from '$lib/i18n';
  import { columnClass, h1Class, introClass, pageClass } from '$lib/text-page';
  import { cn } from '$lib/utils';
  import Search from '@lucide/svelte/icons/search';
  let lang = $derived((page.params.lang || 'de') as Lang);
  let t = $derived(errorPage[lang]);
  let notFound = $derived(page.status === 404);
  // Without the API the app has no data. A crawler that robots.txt keeps off /api/ renders the
  // page that way: it should see the fact sheet and the title the server wrote
  // (server/src/site.rs), not an error, so they stay in place of this page.
  const facts = typeof document === 'undefined' ? null : document.getElementById('oc-facts');
  const fallback = page.status === 503 && !!facts?.textContent?.trim();
  onMount(() => {
    if (fallback && facts) {
      facts.dataset.keep = 'true';
      facts.style.display = 'block';
    }
  });
</script>

<svelte:head
  >{#if !fallback}<title>{page.status} · Tractanda</title>{/if}</svelte:head
>

{#if !fallback}
  <section class={cn('error-page', pageClass, 'pb-8 sm:pt-20')}>
    <div class={columnClass}>
      <p class="text-sm font-medium text-primary">{t.status} {page.status}</p>
      <h1 class={cn(h1Class, 'mt-2')}>{notFound ? t.notFoundTitle : t.errorTitle}</h1>
      <p class={introClass}>{notFound ? t.notFound : copy[lang].unavailable}</p>
      <div class="mt-8 flex flex-wrap gap-3">
        <Button href={href('/', lang)}>{t.home}</Button>
        <Button variant="outline" href={href('/suche', lang)}
          ><Search aria-hidden="true" />{copy[lang].search}</Button
        >
      </div>
    </div>
  </section>
{/if}
