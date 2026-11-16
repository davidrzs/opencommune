<script lang="ts">
  // The Tractanda mark (an agenda of three items) and the name.
  import { cn } from '$lib/utils';
  let { class: className = '', mark = 'size-6' }: { class?: string; mark?: string } = $props();
</script>

<span class={cn('inline-flex items-center gap-2.5', className)}>
  <svg
    viewBox="0 0 24 24"
    class={cn('shrink-0 text-brand', mark)}
    aria-hidden="true"
    focusable="false"
  >
    <rect x="2" y="3.5" width="3" height="3" fill="currentColor" />
    <rect x="8" y="4" width="14" height="2" fill="currentColor" />
    <rect x="2" y="9.5" width="3" height="3" fill="currentColor" />
    <rect x="8" y="10" width="14" height="2" fill="currentColor" />
    <rect x="2" y="15.5" width="3" height="3" fill="currentColor" />
    <rect x="8" y="16" width="9" height="2" fill="currentColor" />
  </svg>
  <span class="font-semibold tracking-tight">Tractanda</span>
</span>
