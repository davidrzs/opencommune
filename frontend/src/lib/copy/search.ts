import type { Lang } from '$lib/i18n';

// Texts of the search page and the document list that i18n.ts does not hold.
export const searchCopy: Record<
  Lang,
  {
    about: string;
    inText: string;
    inTitles: string;
    bestFirst: string;
    newestFirst: string;
    filters: string;
    pages: string;
    pageOf: string;
    tips: string;
    firstFamily: string;
  }
> = {
  de: {
    about: 'zu «{q}»',
    inText: 'Gesucht im Text der Seiten',
    inTitles: 'Gesucht in den Titeln',
    bestFirst: 'Beste Treffer zuerst',
    newestFirst: 'Neueste zuerst',
    filters: 'Filter',
    pages: 'Seiten der Ergebnisse',
    pageOf: 'Seite {n} von {total}',
    tips: 'Suchtipps',
    firstFamily: 'Erster Teil:'
  },
  fr: {
    about: 'pour « {q} »',
    inText: 'Recherche dans le texte des pages',
    inTitles: 'Recherche dans les titres',
    bestFirst: 'Meilleurs résultats d’abord',
    newestFirst: 'Plus récents d’abord',
    filters: 'Filtres',
    pages: 'Pages de résultats',
    pageOf: 'Page {n} sur {total}',
    tips: 'Conseils de recherche',
    firstFamily: 'Première partie :'
  },
  it: {
    about: 'per «{q}»',
    inText: 'Ricerca nel testo delle pagine',
    inTitles: 'Ricerca nei titoli',
    bestFirst: 'Prima i risultati migliori',
    newestFirst: 'Prima i più recenti',
    filters: 'Filtri',
    pages: 'Pagine dei risultati',
    pageOf: 'Pagina {n} di {total}',
    tips: 'Consigli di ricerca',
    firstFamily: 'Prima parte:'
  }
};
