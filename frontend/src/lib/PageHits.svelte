<script lang="ts">
  import { marked, originalLink } from './documents';
  import { copy, fmt, label, type Lang } from './i18n';
  import type { PageHit, Section } from './types';
  // A document's best pages in a full-text search: the page with a link to the original there, the
  // types of the sections that hold it, and the snippet with the matched words marked. `matching`:
  // how many of its pages match. `at`: the commune whose link to the original is used.
  let {
    hits,
    matching,
    sections,
    languages,
    lang,
    at
  }: {
    hits: PageHit[];
    matching: number;
    sections: Section[];
    languages: string[];
    lang: Lang;
    at?: number;
  } = $props();
  let t = $derived(copy[lang]);

  const types = (hit: PageHit) =>
    [...new Set(hit.section_types)].map((type) => label(lang, 'section', type)).join(', ');
  // the colour of the first section that holds the page (DocumentRow sets the family colours)
  const family = (hit: PageHit) =>
    sections.find(
      (s) => s.type === hit.section_types[0] && s.first_page <= hit.page && hit.page <= s.last_page
    )?.family ?? 'other';
  // the snippet's language, when the document has one
  let textLang = $derived(
    languages.length === 1 && languages[0] !== 'other' ? languages[0] : undefined
  );
</script>

<div class="hits mt-3">
  <p class="hits-count text-xs font-medium text-muted-foreground">
    {matching === 1 ? t.matchingPageOne : t.matchingPages.replace('{n}', fmt(matching, lang))}
  </p>
  <ol class="mt-1.5 space-y-2">
    {#each hits as hit (hit.page)}<li
        class="hit family-{family(hit)} rounded-lg border border-border bg-white px-3 py-2.5"
      >
        <p class="hit-meta flex flex-wrap items-center gap-x-1.5 text-xs text-muted-foreground">
          <a
            class="font-medium text-foreground underline-offset-4 hover:text-primary hover:underline"
            href={originalLink(hit.original_url, at)}
            target="_blank"
            rel="nofollow noreferrer"
            title={t.openAt.replace('{n}', fmt(hit.page, lang))}
            >{t.pageAbbr} {fmt(hit.page, lang)} ↗</a
          >{#if hit.section_types.length}{' · '}<span class="inline-flex items-center gap-1.5"
              ><i class="size-2 rounded-full bg-(--family)" aria-hidden="true"></i>{types(
                hit
              )}</span
            >{/if}
        </p>
        <p
          class="snippet mt-1 text-sm leading-relaxed text-zinc-700 [overflow-wrap:anywhere]"
          lang={textLang}
        >
          {#each marked(hit.snippet, hit.highlights) as run}{#if run.marked}<mark
                class="rounded-sm bg-primary/10 font-medium text-foreground">{run.text}</mark
              >{:else}{run.text}{/if}{/each}
        </p>
      </li>{/each}
  </ol>
</div>
