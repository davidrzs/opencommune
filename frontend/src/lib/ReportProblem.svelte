<script lang="ts">
  import { about } from '$lib/about';
  import { onMount } from 'svelte';
  import { copy, type Lang } from '$lib/i18n';
  import { cn } from '$lib/utils';

  let {
    lang,
    entry = '',
    source = '',
    mode = 'report',
    class: className = ''
  }: {
    lang: Lang;
    entry?: string;
    source?: string;
    mode?: 'report' | 'contact';
    class?: string;
  } = $props();
  let label = $derived(mode === 'contact' ? about[lang].email : copy[lang].report);
  let t = $derived(copy[lang]);
  let address = $state('');
  let ready = $state(false);
  let draft = $state('');
  onMount(() => {
    ready = true;
  });

  function prepare(event: MouseEvent & { currentTarget: HTMLAnchorElement }) {
    // Obfuscation against basic HTML scrapers, not encryption.
    address = String.fromCharCode(122, 100, 97, 118, 105, 100, 64, 101, 116, 104, 122, 46, 99, 104);
    const body =
      mode === 'contact'
        ? ''
        : [
            t.reportPrompt,
            '',
            '',
            `${t.reportPage}: ${window.location.href}`,
            ...(entry ? [`${t.reportEntry}: ${entry}`] : []),
            ...(source ? [`${t.source}: ${source}`] : [])
          ].join('\n');
    draft = `mailto:${address}?subject=${encodeURIComponent(`Tractanda: ${mode === 'contact' ? about[lang].emailSubject : t.report}`)}&body=${encodeURIComponent(body)}`;
    event.currentTarget.href = draft;
  }
</script>

<!-- inline, so that the line it sits in (the band, the footer list, a document row) keeps its layout -->
<span class="report-action">
  <a
    href={draft || '#report'}
    onclick={prepare}
    aria-disabled={!ready}
    title={t.reportHint}
    class={cn(
      'rounded-sm text-inherit underline-offset-4 hover:text-foreground hover:underline focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:outline-none',
      className
    )}
    data-report-email>{label}</a
  >
  {#if address}<span class="report-address ml-2 break-all select-all" aria-live="polite"
      >{t.reportAddress}: {address}</span
    >{/if}
</span>
