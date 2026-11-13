<script lang="ts">
  import { page } from '$app/state';
  import { apiPage } from '$lib/api-page';
  import { type Lang } from '$lib/i18n';
  let lang = $derived((page.params.lang || 'de') as Lang);
  let t = $derived(apiPage[lang]);
  let mcpUrl = $derived(`${page.url.origin}/mcp`);
  let snippet = $derived(JSON.stringify({ mcpServers: { opencommune: { url: mcpUrl } } }, null, 2));
  let copied = $state(false);
  async function copySnippet() {
    try {
      await navigator.clipboard.writeText(snippet);
      copied = true;
      setTimeout(() => (copied = false), 2000);
    } catch {
      // the snippet stays selectable by hand
    }
  }

  // Scalar's colours and fonts from our tokens; its own layout otherwise
  const customCss = `
    .scalar-app {
      --scalar-font: var(--font-family);
      --scalar-font-code: var(--font-family-mono);
      --scalar-color-1: var(--ink);
      --scalar-color-2: var(--muted);
      --scalar-color-3: var(--faint);
      --scalar-color-accent: var(--accent);
      --scalar-background-1: var(--paper);
      --scalar-background-2: var(--band);
      --scalar-background-3: var(--line);
      --scalar-border-color: var(--line);
      --scalar-radius: 0;
      --scalar-radius-lg: 0;
      --scalar-radius-xl: 0;
    }
    /* links that would hand this site's description to Scalar's hosted client */
    .scalar-app a[href^='https://client.scalar.com'] {
      display: none;
    }`;

  // The interactive reference: loaded only on this page, from this site only. No Scalar fonts, no
  // request proxy, no telemetry, no AI agent, no developer tools, no link to Scalar's hosted
  // client; "try it" goes to this origin.
  let container: HTMLDivElement;
  let status = $state<'loading' | 'ready' | 'failed'>('loading');
  $effect(() => {
    // Scalar has German and French; Italian falls back to English
    const locale = lang === 'it' ? 'en' : lang;
    const origin = page.url.origin;
    let instance: { destroy: () => void } | undefined;
    let stopped = false;
    status = 'loading';
    Promise.all([import('@scalar/api-reference'), import('@scalar/api-reference/style.css')])
      .then(([{ createApiReference }]) => {
        if (stopped) return;
        instance = createApiReference(container, {
          url: '/api/openapi.json',
          servers: [{ url: origin }],
          withDefaultFonts: false,
          telemetry: false,
          agent: { disabled: true },
          mcp: { disabled: true },
          showDeveloperTools: 'never',
          hideClientButton: true,
          hideDarkModeToggle: true,
          forceDarkModeState: 'light',
          documentDownloadType: 'json',
          defaultHttpClient: { targetKey: 'shell', clientKey: 'curl' },
          localization: { locale },
          theme: 'default',
          customCss,
          _integration: 'svelte'
        });
        status = 'ready';
      })
      .catch(() => {
        if (!stopped) status = 'failed';
      });
    return () => {
      stopped = true;
      instance?.destroy();
    };
  });
</script>

<svelte:head>
  <title>{t.title} — OpenCommune</title>
  <meta name="description" content={t.intro} />
</svelte:head>

<article class="api-page container">
  <header>
    <h1>{t.title}</h1>
    <p class="intro">{t.intro}</p>
    <p>{t.license}</p>
    <p>{t.caveat}</p>
    <a class="text-link" href="/api/openapi.json" target="_blank" rel="noreferrer">{t.openapi} ↗</a>
  </header>
  <section class="mcp">
    <h2>{t.mcpTitle}</h2>
    <p>
      {t.mcp.split('{url}')[0]}<code>{mcpUrl}</code>{t.mcp.split('{url}')[1]}
    </p>
    <p>{t.mcpConfig}</p>
    <div class="snippet">
      <pre><code>{snippet}</code></pre>
      <button type="button" onclick={copySnippet}>{copied ? t.copied : t.copy}</button>
    </div>
    <p>{t.mcpConnector}</p>
  </section>
  <section class="reference" aria-labelledby="reference-title">
    <h2 id="reference-title">{t.referenceTitle}</h2>
    <p>{t.referenceNote}</p>
    {#if status === 'loading'}<p class="small-note">{t.loading}</p>{:else if status === 'failed'}<p
        class="small-note"
      >
        {t.failed}
      </p>{/if}
  </section>
</article>
<div class="scalar container" bind:this={container}></div>

<style>
  .api-page {
    padding-top: var(--space-7xl);
  }
  .api-page > * {
    max-width: var(--measure);
  }
  h1 {
    font-size: var(--font-size-page-title);
    line-height: var(--line-height-tight);
    letter-spacing: var(--letter-spacing-tight);
  }
  h2 {
    font-size: var(--font-size-2xl);
    line-height: var(--line-height-snug);
    margin-bottom: var(--space-md);
  }
  section {
    margin-top: var(--space-5xl);
  }
  p {
    font-size: var(--font-size-lg);
    line-height: var(--line-height-loose);
    color: var(--muted);
    margin: var(--space-md) 0;
  }
  .intro {
    font-size: var(--font-size-2xl);
    line-height: var(--line-height-normal);
    color: var(--ink);
    margin-top: var(--space-2xl);
  }
  code {
    font-family: var(--font-family-mono);
    font-size: var(--font-size-code);
    color: var(--ink);
    overflow-wrap: anywhere;
  }
  .snippet {
    display: flex;
    align-items: flex-start;
    gap: var(--space-md);
    background: var(--band);
    border: var(--rule);
    padding: var(--space-md) var(--space-lg);
  }
  .snippet pre {
    flex: 1;
    min-width: 0;
    margin: 0;
    overflow-x: auto;
  }
  .snippet button {
    font-size: var(--font-size-md);
    padding: var(--space-xs) var(--space-md);
  }
  .scalar {
    margin-top: var(--space-2xl);
    padding-bottom: var(--space-7xl);
  }
  @media (max-width: 600px) {
    .api-page {
      padding-top: var(--space-4xl);
    }
    .snippet {
      flex-direction: column;
    }
  }
</style>
