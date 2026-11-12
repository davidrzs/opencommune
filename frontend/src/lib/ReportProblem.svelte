<script lang="ts">
  import { about } from '$lib/about';
  import { onMount } from 'svelte';
  import { copy, type Lang } from '$lib/i18n';

  let {
    lang,
    entry = '',
    source = '',
    mode = 'report'
  }: { lang: Lang; entry?: string; source?: string; mode?: 'report' | 'contact' } = $props();
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
    draft = `mailto:${address}?subject=${encodeURIComponent(`OpenCommune: ${mode === 'contact' ? about[lang].emailSubject : t.report}`)}&body=${encodeURIComponent(body)}`;
    event.currentTarget.href = draft;
  }
</script>

<span class="report-action">
  <a
    href={draft || '#report'}
    onclick={prepare}
    aria-disabled={!ready}
    title={t.reportHint}
    data-report-email>{label}</a
  >
  {#if address}<span class="report-address" aria-live="polite">{t.reportAddress}: {address}</span
    >{/if}
</span>

<style>
  .report-action {
    display: inline-block;
    font-size: 13px;
    color: var(--muted, #626872);
  }
  .report-address {
    display: block;
    overflow-wrap: anywhere;
    user-select: all;
    margin-top: 6px;
  }
  a {
    text-underline-offset: 3px;
  }
  :global(.document-row) .report-action {
    margin-left: 18px;
  }
</style>
