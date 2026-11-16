<script lang="ts">
  import { page } from '$app/state';
  import { credits, licensesPage, local } from '$lib/copy/pages';
  import type { Lang } from '$lib/i18n';
  import {
    columnClass,
    h1Class,
    h2Class,
    h3Class,
    introClass,
    linkClass,
    pClass,
    pageClass,
    sectionClass
  } from '$lib/text-page';
  import { cn } from '$lib/utils';
  import ArrowUpRight from '@lucide/svelte/icons/arrow-up-right';
  let lang = $derived((page.params.lang || 'de') as Lang);
  let t = $derived(licensesPage[lang]);
  // French sets a space before the colon
  let colon = $derived(lang === 'fr' ? '\u00a0:' : ':');
  let own = $derived([
    {
      what: t.code,
      text: t.codeText,
      license: 'MIT',
      licenseHref: 'https://opensource.org/license/mit',
      where: t.codeWhere,
      href: 'https://github.com/davidrzs/tractanda'
    },
    {
      what: t.data,
      text: t.dataText,
      license: 'CC0 1.0',
      licenseHref: 'https://creativecommons.org/publicdomain/zero/1.0/',
      where: t.dataWhere,
      href: 'https://huggingface.co/datasets/davidrzs/tractanda'
    }
  ]);
</script>

<svelte:head>
  <title>{t.title} — Tractanda</title>
  <meta name="description" content={t.intro} />
</svelte:head>

<article class={cn('licenses-page', pageClass)}>
  <div class={columnClass}>
    <header>
      <h1 class={h1Class}>{t.title}</h1>
      <p class={introClass}>{t.intro}</p>
    </header>

    <section class={sectionClass} aria-labelledby="own">
      <h2 id="own" class={h2Class}>{t.ownTitle}</h2>
      <dl class="mt-4 grid gap-3 sm:grid-cols-2">
        {#each own as item}
          <div class="rounded-lg border border-border p-4">
            <dt class="text-sm text-muted-foreground">{item.what}</dt>
            <dd class="mt-1">
              <a class={cn(linkClass, 'text-lg font-semibold')} href={item.licenseHref}
                >{item.license}</a
              >
              <p class="mt-2 text-sm leading-6 text-zinc-700">{item.text}</p>
              <p class="mt-3 text-sm">
                <a
                  class={cn('text-link inline-flex items-center gap-1', linkClass)}
                  href={item.href}>{item.where}<ArrowUpRight class="size-4" aria-hidden="true" /></a
                >
              </p>
            </dd>
          </div>
        {/each}
      </dl>
      <p class={pClass}>{t.ownNote}</p>
    </section>

    <section class={sectionClass} aria-labelledby="credits">
      <h2 id="credits" class={h2Class}>{t.creditsTitle}</h2>
      <p class={pClass}>{t.creditsIntro}</p>
      {#each credits as group}
        <h3 class={cn(h3Class, 'mt-8')}>{local(group.title, lang)}</h3>
        <ul class="mt-3 divide-y divide-border border-y border-border">
          {#each group.credits as credit}
            <li class="py-4">
              <div
                class="flex flex-col gap-1 sm:flex-row sm:items-baseline sm:justify-between sm:gap-6"
              >
                <p class="font-medium">
                  {#if credit.href}<a class={linkClass} href={credit.href}
                      >{local(credit.name, lang)}</a
                    >{:else}{local(credit.name, lang)}{/if}{#if credit.by}<span
                      class="font-normal text-muted-foreground"
                      >{` · ${local(credit.by, lang)}`}</span
                    >{/if}
                </p>
                {#if credit.license}<p class="shrink-0 text-sm text-zinc-600 sm:text-right">
                    {local(credit.license, lang)}
                  </p>{/if}
              </div>
              <p class="mt-1.5 text-sm leading-6 text-zinc-700">{local(credit.use, lang)}</p>
              {#if credit.parts}
                <ul class="mt-2 flex flex-wrap gap-x-5 gap-y-1 text-sm text-zinc-600">
                  {#each credit.parts as part}
                    <li>
                      {#if part.label}{`${local(part.label, lang)}${colon} `}{/if}<a
                        class={cn(linkClass, 'font-normal')}
                        href={part.href}>{part.name}</a
                      ><span class="text-muted-foreground">{` · ${part.license}`}</span>
                    </li>
                  {/each}
                </ul>
              {/if}
            </li>
          {/each}
        </ul>
        {#if group.note}<p class="mt-3 text-sm leading-6 text-zinc-600">
            {local(group.note, lang)}
          </p>{/if}
      {/each}
    </section>
  </div>
</article>
