<script lang="ts">
  import { copy, href, fmt, type Lang } from '$lib/i18n';
  import { DATASET_URL, MCP_COMMAND, SOURCE_URL, docs, start } from '$lib/copy/start';
  import { goto } from '$app/navigation';
  import { page } from '$app/state';
  import Map from '$lib/Map.svelte';
  import CommuneSearch from '$lib/CommuneSearch.svelte';
  import ReportProblem from '$lib/ReportProblem.svelte';
  import { Button } from '$lib/components/ui/button';
  import { Badge } from '$lib/components/ui/badge';
  import { type Commune, hasDocuments } from '$lib/types';
  import Search from '@lucide/svelte/icons/search';
  import Check from '@lucide/svelte/icons/check';
  import Copy from '@lucide/svelte/icons/copy';
  import ArrowUpRight from '@lucide/svelte/icons/arrow-up-right';
  import FileText from '@lucide/svelte/icons/file-text';
  import CodeXml from '@lucide/svelte/icons/code-xml';
  import hfIcon from '$lib/icons/huggingface.svg';
  import ghIcon from '$lib/icons/github.svg';
  let { data } = $props();
  let lang = $derived((page.params.lang || 'de') as Lang);
  let t = $derived(copy[lang]);
  let s = $derived(start[lang]);
  const number = (n: number) => fmt(n, lang);
  let communes = $derived(data.communes as Commune[]);
  let collected = $derived(communes.filter(hasDocuments));
  let lead = $derived(s.lead.replace('{communes}', number(collected.length)));

  // the search of every document's text (the search page reads ?q=)
  let q = $state('');
  const searchHref = (words: string) =>
    href('/suche', lang) + (words ? `?${new URLSearchParams({ q: words })}` : '');
  function search(e: SubmitEvent) {
    e.preventDefault();
    goto(searchHref(q.trim()));
  }

  // the list of communes, most documents first
  const FIRST = 10;
  let canton = $state('');
  let visibleCount = $state(FIRST);
  let shown = $derived(
    communes
      .filter((c) => !canton || c.canton === canton)
      .sort((a, b) => b.documents - a.documents || a.name.localeCompare(b.name, lang))
  );
  let cantons = $derived([...new Set(communes.map((c) => c.canton))].sort());

  let copied = $state(false);
  function copyCommand() {
    navigator.clipboard
      ?.writeText(MCP_COMMAND)
      .then(() => {
        copied = true;
        setTimeout(() => (copied = false), 1500);
      })
      .catch(() => {});
  }

  const card =
    'flex flex-col rounded-xl border border-border p-5 outline-none focus-visible:ring-3 focus-visible:ring-ring/50';
  const cardLink = `${card} hover:border-zinc-300 hover:bg-zinc-50`;
</script>

<svelte:head
  ><title>Tractanda — {s.pageTitle}</title><meta name="description" content={lead} /></svelte:head
>

<section class="mx-auto max-w-7xl px-4 pt-10 pb-12 sm:px-6 sm:pt-14">
  <div class="grid items-start gap-10 lg:grid-cols-12">
    <div class="min-w-0 lg:col-span-5">
      <h1 class="max-w-2xl text-3xl font-semibold tracking-tight sm:text-4xl">{s.title}</h1>
      <p class="mt-3 max-w-2xl text-base text-zinc-600 sm:text-lg">{lead}</p>
      <form class="mt-7 max-w-2xl" role="search" action={href('/suche', lang)} onsubmit={search}>
        <label for="start-q" class="text-sm font-medium text-foreground">{s.searchLabel}</label>
        <div class="mt-2 flex flex-col gap-2 sm:flex-row">
          <div class="relative flex-1">
            <Search
              class="pointer-events-none absolute top-1/2 left-3.5 size-5 -translate-y-1/2 text-zinc-400"
              aria-hidden="true"
            />
            <input
              id="start-q"
              name="q"
              type="search"
              autocomplete="off"
              bind:value={q}
              placeholder={s.searchPlaceholder}
              class="h-11 w-full rounded-lg border border-input bg-white pr-3 pl-11 text-base shadow-xs outline-none placeholder:text-zinc-400 focus-visible:border-zinc-900 focus-visible:ring-4 focus-visible:ring-ring/15"
            />
          </div>
          <Button type="submit" class="h-11 px-6 shadow-xs hover:bg-brand-dark"
            >{t.searchButton}</Button
          >
        </div>
        <div class="mt-3 flex flex-wrap items-center gap-2 text-sm">
          <span class="mr-1 text-muted-foreground">{s.examples}</span>
          {#each s.exampleQueries as example}<a
              href={searchHref(example)}
              class="rounded-md border border-border px-2.5 py-1 text-zinc-700 outline-none hover:bg-zinc-50 hover:text-foreground focus-visible:ring-3 focus-visible:ring-ring/50"
              >{example}</a
            >{/each}
        </div>
      </form>
      <div class="index-intro mt-6 max-w-2xl text-sm text-muted-foreground">
        {#await data.files then files}{#if files !== null}<h2 class="inline font-normal">
              {t.archiveTotal
                .replace('{documents}', number(files))
                .replace('{communes}', number(collected.length))}
            </h2>
            <span aria-hidden="true">·</span>{/if}{/await}
        {s.machineNote}
      </div>
    </div>
    <div class="min-w-0 lg:col-span-7">
      <CommuneSearch {communes} />
      <div class="mt-4"><Map {communes} /></div>
    </div>
  </div>
</section>

<section id="gemeinden" class="border-t border-border">
  <div class="mx-auto max-w-7xl px-4 py-12 sm:px-6">
    <div class="max-w-3xl">
      <div class="flex flex-wrap items-center justify-between gap-3">
        <h2 class="text-xl font-semibold tracking-tight">{t.discover}</h2>
        <label
          ><span class="sr-only">{t.cantonLabel}</span><select
            bind:value={canton}
            onchange={() => (visibleCount = FIRST)}
            class="h-9 rounded-md border border-input bg-white px-2 text-sm shadow-xs outline-none focus-visible:ring-4 focus-visible:ring-ring/15"
            ><option value="">{t.allCantons}</option>{#each cantons as c}<option>{c}</option
              >{/each}</select
          ></label
        >
      </div>
      <p class="coverage-count mt-1 text-muted-foreground">
        <strong class="font-medium text-foreground">{number(collected.length)}</strong>
        {t.withDocuments}. {t.coverageNote}
      </p>
      <div class="communes-list -mx-2 mt-5 divide-y divide-border border-y border-border">
        {#each shown.slice(0, visibleCount) as c (c.bfs_id)}<a
            class="commune-row flex items-center justify-between gap-3 rounded-md px-2 py-2.5 text-sm text-foreground outline-none hover:bg-zinc-50 focus-visible:ring-3 focus-visible:ring-ring/50"
            href={href(`/gemeinden/${c.bfs_id}`, lang)}
            ><span class="min-w-0 flex-1 truncate"
              >{c.name} <small class="text-[13px] text-muted-foreground">{c.canton}</small></span
            ><span class="shrink-0 text-[13px] text-muted-foreground"
              >{c.documents ? docs(c.documents, lang) : t.missing}</span
            ><ArrowUpRight class="size-3.5 shrink-0 text-zinc-400" aria-hidden="true" /></a
          >{/each}
      </div>
      <div class="mt-4 flex flex-wrap items-center justify-between gap-x-6 gap-y-3 text-sm">
        <p class="text-muted-foreground">
          <!-- the heading counts the communes with documents; a second total here would differ -->
          {#if canton}{s.communeCount.replace('{n}', number(shown.length))} ·
          {/if}{s.byCount}
        </p>
        <div class="flex flex-wrap items-center gap-x-6 gap-y-3">
          {#if visibleCount < shown.length}
            <Button
              variant="outline"
              class="load-more h-9 px-3"
              onclick={() => (visibleCount += 50)}>{t.moreCommunes}</Button
            >
          {/if}
          <a
            class="text-link font-medium text-foreground underline decoration-zinc-300 underline-offset-4 hover:decoration-zinc-900"
            href={href('/suche', lang)}>{t.topicLink}</a
          >
        </div>
      </div>
    </div>
  </div>
</section>

<section id="offen" class="border-t border-border">
  <div class="mx-auto max-w-7xl px-4 py-12 sm:px-6">
    <h2 class="text-xl font-semibold tracking-tight">{s.openTitle}</h2>
    <p class="mt-1 text-zinc-600">{s.openIntro}</p>
    <div class="mt-8 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
      <a href={SOURCE_URL} class={cardLink}>
        <img src={ghIcon} alt="" class="size-5" />
        <span class="mt-4 inline-flex items-center gap-1 font-medium"
          >{s.codeTitle}<ArrowUpRight class="size-3.5 text-zinc-400" aria-hidden="true" /></span
        >
        <span class="mt-1 text-sm text-zinc-600">{s.codeText}</span>
      </a>
      <a href={DATASET_URL} class={cardLink}>
        <img src={hfIcon} alt="" class="size-5" />
        <span class="mt-4 inline-flex items-center gap-1 font-medium"
          >{s.dataTitle}<ArrowUpRight class="size-3.5 text-zinc-400" aria-hidden="true" /></span
        >
        <span class="mt-1 text-sm text-zinc-600">{s.dataText}</span>
      </a>
      <div class={card}>
        <FileText class="size-5 text-zinc-700" strokeWidth={1.8} aria-hidden="true" />
        <span class="mt-4 inline-flex items-center gap-2 font-medium"
          >{s.paperTitle}
          <Badge variant="secondary" class="font-normal text-zinc-600">{s.soon}</Badge></span
        >
        <span class="mt-1 text-sm text-zinc-600">{s.paperText}</span>
      </div>
      <a href={href('/api', lang)} class={cardLink}>
        <CodeXml class="size-5 text-zinc-700" strokeWidth={1.8} aria-hidden="true" />
        <span class="mt-4 font-medium">{s.apiTitle}</span>
        <span class="mt-1 text-sm text-zinc-600">{s.apiText}</span>
      </a>
    </div>
    <p class="mt-6 text-sm text-muted-foreground">{s.mcpLabel}</p>
    <div
      class="mt-2 flex min-w-0 items-center justify-between gap-3 rounded-lg bg-zinc-950 py-2 pr-2 pl-4 font-mono text-sm text-zinc-100"
    >
      <code class="min-w-0 overflow-x-auto py-1 whitespace-nowrap">{MCP_COMMAND}</code>
      <button
        type="button"
        onclick={copyCommand}
        aria-label={s.copyLabel}
        class="inline-flex shrink-0 items-center gap-1.5 rounded-md px-2 py-1 font-sans text-xs text-zinc-400 outline-none hover:bg-zinc-800 hover:text-white focus-visible:ring-2 focus-visible:ring-zinc-400"
        ><Copy class="size-3.5" aria-hidden="true" />{copied ? s.copied : s.copy}</button
      >
      <span class="sr-only" aria-live="polite">{copied ? s.copied : ''}</span>
    </div>
  </div>
</section>

<section id="sammeln" class="border-t border-border">
  <div class="mx-auto grid max-w-7xl gap-8 px-4 py-12 sm:px-6 lg:grid-cols-12">
    <div class="lg:col-span-5">
      <h2 class="text-xl font-semibold tracking-tight">{s.collectTitle}</h2>
      <p class="mt-1 max-w-md text-zinc-600">{s.collectIntro}</p>
      <a
        class="mt-3 inline-block text-sm font-medium text-foreground underline decoration-zinc-300 underline-offset-4 hover:decoration-zinc-900"
        href={href('/ueber-uns', lang)}>{s.aboutLink}</a
      >
    </div>
    <ul class="space-y-3 text-zinc-700 lg:col-span-7">
      {#each s.rules as rule, i}<li class="flex gap-3">
          <Check
            class="mt-1 size-4 shrink-0 text-brand"
            strokeWidth={2.4}
            aria-hidden="true"
          /><span
            >{rule}{#if i === 4}{' '}<span
                class="[&_a]:font-medium [&_a]:text-foreground [&_a]:underline [&_a]:decoration-zinc-300 [&_a]:underline-offset-4 [&_a:hover]:decoration-zinc-900"
                ><ReportProblem {lang} /></span
              >{/if}</span
          >
        </li>{/each}
    </ul>
  </div>
</section>
