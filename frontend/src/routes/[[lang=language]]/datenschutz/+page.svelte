<script lang="ts">
  import { page } from '$app/state';
  import { privacy } from '$lib/privacy';
  import { type Lang } from '$lib/i18n';
  import {
    columnClass,
    h1Class,
    h2Class,
    introClass,
    linkClass,
    pClass,
    pageClass,
    sectionClass
  } from '$lib/text-page';
  import { cn } from '$lib/utils';
  import Mail from '@lucide/svelte/icons/mail';
  let lang = $derived((page.params.lang || 'de') as Lang);
  let t = $derived(privacy[lang]);
</script>

<svelte:head>
  <title>{t.title} — Tractanda</title>
  <meta name="description" content={t.intro} />
</svelte:head>

<article class={cn('privacy-page', pageClass)}>
  <div class={columnClass}>
    <header>
      <h1 class={h1Class}>{t.title}</h1>
      <p class="updated mt-2 text-sm text-muted-foreground">{t.updated}</p>
      <p class={introClass}>{t.intro}</p>
    </header>
    <div class="sections">
      {#each t.sections as section}<section class={sectionClass}>
          <h2 class={h2Class}>{section.title}</h2>
          {#each section.paragraphs as paragraph}<p class={pClass}>{paragraph}</p>{/each}
        </section>{/each}
    </div>
    <p class={cn(sectionClass, 'text-sm')}>
      <a
        class={cn('text-link inline-flex items-center gap-1.5', linkClass)}
        href={`mailto:zdavid@ethz.ch?subject=${encodeURIComponent(t.title)}`}
        ><Mail class="size-4" aria-hidden="true" />{t.contact}</a
      >
    </p>
  </div>
</article>
