<script lang="ts">
  // A field that suggests communes by name; a suggestion opens the commune's page. Arrow keys
  // move through the suggestions, Enter opens one, Escape closes the list.
  import { copy, href, type Lang } from '$lib/i18n';
  import { docs } from '$lib/copy/start';
  import { goto } from '$app/navigation';
  import { page } from '$app/state';
  import Search from '@lucide/svelte/icons/search';
  import type { Commune } from './types';
  import { otherNames, searchKey } from './commune-names';
  let { communes }: { communes: Commune[] } = $props();
  let lang = $derived((page.params.lang || 'de') as Lang);
  let t = $derived(copy[lang]);
  const id = $props.id();
  let query = $state('');
  let open = $state(false);
  let active = $state(-1);
  // every name of each commune: the official one, then its names in the other languages
  let names = $derived(
    communes.map((c) => ({
      c,
      names: [c.name, ...(otherNames[c.bfs_id] ?? [])].map((n) => [n, searchKey(n)] as const)
    }))
  );
  // names that start with the words first, then names that contain them; `as` is the other name
  // that matched, shown next to the official one
  let matches = $derived.by(() => {
    const q = searchKey(query);
    if (!q) return [];
    const first = (test: (key: string) => boolean) =>
      names.flatMap(({ c, names }) => {
        const hit = names.find(([, key]) => test(key));
        return hit ? [{ ...c, as: hit[0] === c.name ? null : hit[0] }] : [];
      });
    const starting = first((key) => key.startsWith(q));
    const seen = new Set(starting.map((c) => c.bfs_id));
    const containing = first((key) => key.includes(q)).filter((c) => !seen.has(c.bfs_id));
    return [...starting, ...containing].slice(0, 8);
  });
  let expanded = $derived(open && matches.length > 0);
  const link = (c: Commune) => href(`/gemeinden/${c.bfs_id}`, lang);

  function keydown(e: KeyboardEvent) {
    if (e.key === 'ArrowDown' && matches.length) {
      open = true;
      active = Math.min(active + 1, matches.length - 1);
    } else if (e.key === 'ArrowUp' && matches.length) {
      active = Math.max(active - 1, 0);
    } else if (e.key === 'Enter' && open && matches.length) {
      goto(link(matches[Math.max(active, 0)]));
    } else if (e.key === 'Escape' && open) {
      open = false;
      active = -1;
    } else return;
    e.preventDefault();
  }
</script>

<div class="commune-search relative z-20">
  <label for="{id}-input" class="text-sm font-medium text-foreground">{t.find}</label>
  <div class="relative mt-2">
    <Search
      class="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-zinc-400"
      aria-hidden="true"
    />
    <input
      id="{id}-input"
      bind:value={query}
      oninput={() => {
        open = true;
        active = -1;
      }}
      onfocus={() => (open = true)}
      onblur={() => {
        open = false;
        active = -1;
      }}
      onkeydown={keydown}
      placeholder={t.placeholder}
      autocomplete="off"
      spellcheck="false"
      type="text"
      role="combobox"
      aria-autocomplete="list"
      aria-expanded={expanded}
      aria-controls="{id}-list"
      aria-activedescendant={expanded && active >= 0
        ? `${id}-${matches[active].bfs_id}`
        : undefined}
      aria-describedby="{id}-hint"
      class="h-10 w-full rounded-lg border border-input bg-white pr-3 pl-9 text-base shadow-xs outline-none placeholder:text-zinc-400 focus-visible:border-zinc-900 focus-visible:ring-4 focus-visible:ring-ring/15 sm:text-sm"
    />
    <!-- mousedown would move the focus away from the field and close the list before the click -->
    <div
      id="{id}-list"
      role="listbox"
      tabindex="-1"
      aria-label={t.communes}
      hidden={!expanded}
      class="suggestions absolute z-10 mt-1 w-full rounded-lg border border-border bg-white p-1 shadow-lg"
      onmousedown={(e) => e.preventDefault()}
    >
      {#each matches as c, i (c.bfs_id)}<a
          id="{id}-{c.bfs_id}"
          href={link(c)}
          role="option"
          tabindex="-1"
          aria-selected={i === active}
          class="flex items-center justify-between gap-3 rounded-md px-3 py-2 text-sm text-foreground hover:bg-muted aria-selected:bg-muted"
          ><span class="min-w-0 truncate"
            >{c.name}{#if c.as}<span class="text-muted-foreground"> ({c.as})</span>{/if}
            <small class="text-[13px] text-muted-foreground">{c.canton}</small></span
          ><small class="shrink-0 text-[13px] text-muted-foreground"
            >{c.documents ? docs(c.documents, lang) : '–'}</small
          ></a
        >{/each}
    </div>
    {#if open && query.trim() && !matches.length}<p
        class="absolute z-10 mt-1 w-full rounded-lg border border-border bg-white px-4 py-3 text-sm text-muted-foreground shadow-lg"
      >
        {t.noMatch}
      </p>{/if}
  </div>
  <p id="{id}-hint" class="sr-only" aria-live="polite">
    {query.trim() ? (matches.length ? `${matches.length} ${t.communes}` : t.noMatch) : ''}
  </p>
</div>
