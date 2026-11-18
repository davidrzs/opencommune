// Texts of the licences page (/lizenzen) and the error page. Every licence named here was checked
// against the work's own metadata: package.json, the installed Python packages, `cargo metadata`,
// the model and dataset cards, the terms of swisstopo and the BFS.
import type { Lang } from '$lib/i18n';

type Text = Record<Lang, string>;
// a part of a credited work: a model, a dataset, a library it is built with
export type Part = { label?: Text; name: string; href: string; license: string };
export type Credit = {
  name: string | Text;
  href?: string;
  by?: string | Text;
  license?: string | Text;
  use: Text;
  parts?: Part[];
};
export type CreditGroup = { title: Text; credits: Credit[]; note?: Text };

export const local = (value: string | Text, lang: Lang) =>
  typeof value === 'string' ? value : value[lang];

export const licensesPage = {
  de: {
    title: 'Lizenzen und Dank',
    intro:
      'Diese Seite nennt die Lizenzen von Code und Daten und die Arbeit anderer, auf der Tractanda aufbaut.',
    ownTitle: 'Code und Daten von Tractanda',
    code: 'Quellcode',
    codeText: 'Crawler, Verarbeitung, Server und Website.',
    codeWhere: 'GitHub',
    data: 'Daten',
    dataText:
      'Die Angaben, die Tractanda aus den Dokumenten gewinnt: Verzeichnis, Titel, Gremien, Daten und Teile.',
    dataWhere: 'Hugging Face und API',
    ownNote:
      'CC0 1.0 bedeutet: Die Daten dürfen ohne Bedingungen genutzt werden. Eine Quellenangabe ist nicht nötig, aber willkommen. Die Dokumente selbst sind Veröffentlichungen der Gemeinden; Tractanda verweist auf das Original.',
    creditsTitle: 'Dank',
    creditsIntro:
      'Tractanda beruht auf offener Software, offenen Modellen und offenen Daten. Wir danken allen, die sie geschaffen haben und pflegen.'
  },
  fr: {
    title: 'Licences et remerciements',
    intro:
      'Cette page indique les licences du code et des données, et les travaux d’autres personnes sur lesquels Tractanda s’appuie.',
    ownTitle: 'Code et données de Tractanda',
    code: 'Code source',
    codeText: 'Robot d’indexation, traitement, serveur et site web.',
    codeWhere: 'GitHub',
    data: 'Données',
    dataText:
      'Les informations que Tractanda tire des documents : répertoire, titres, organes, dates et parties.',
    dataWhere: 'Hugging Face et API',
    ownNote:
      'CC0 1.0 signifie que les données peuvent être utilisées sans condition. Citer la source n’est pas obligatoire, mais apprécié. Les documents eux-mêmes sont des publications des communes ; Tractanda renvoie à l’original.',
    creditsTitle: 'Remerciements',
    creditsIntro:
      'Tractanda repose sur des logiciels, des modèles et des données ouverts. Nous remercions toutes les personnes qui les ont créés et les entretiennent.'
  },
  it: {
    title: 'Licenze e ringraziamenti',
    intro:
      'Questa pagina indica le licenze del codice e dei dati e il lavoro altrui su cui si basa Tractanda.',
    ownTitle: 'Codice e dati di Tractanda',
    code: 'Codice sorgente',
    codeText: 'Crawler, elaborazione, server e sito web.',
    codeWhere: 'GitHub',
    data: 'Dati',
    dataText:
      'Le informazioni che Tractanda ricava dai documenti: elenco, titoli, organi, date e parti.',
    dataWhere: 'Hugging Face e API',
    ownNote:
      'CC0 1.0 significa che i dati possono essere usati senza condizioni. Citare la fonte non è obbligatorio, ma è gradito. I documenti stessi sono pubblicazioni dei comuni; Tractanda rimanda all’originale.',
    creditsTitle: 'Ringraziamenti',
    creditsIntro:
      'Tractanda si basa su software, modelli e dati aperti. Ringraziamo tutte le persone che li hanno creati e li mantengono.'
  },
  en: {
    title: 'Licences and thanks',
    intro:
      'This page names the licences of the code and the data, and the work of others on which Tractanda builds.',
    ownTitle: 'Tractanda’s code and data',
    code: 'Source code',
    codeText: 'Crawler, processing, server and website.',
    codeWhere: 'GitHub',
    data: 'Data',
    dataText:
      'The information Tractanda draws from the documents: register, titles, bodies, dates and parts.',
    dataWhere: 'Hugging Face and API',
    ownNote:
      'CC0 1.0 means that the data may be used without conditions. Citing the source is not required, but welcome. The documents themselves are publications of the municipalities; Tractanda links to the original.',
    creditsTitle: 'Thanks',
    creditsIntro:
      'Tractanda is built on open software, open models and open data. We thank everyone who has created and maintains them.'
  }
};

export const credits: CreditGroup[] = [
  {
    title: {
      de: 'Dokumente lesen und erschliessen',
      fr: 'Lire et exploiter les documents',
      it: 'Leggere e indicizzare i documenti',
      en: 'Reading and indexing the documents'
    },
    credits: [
      {
        name: 'gheim',
        href: 'https://github.com/joelbarmettlerUZH/gheim',
        by: 'Joel Barmettler',
        license: 'Apache-2.0',
        use: {
          de: 'Findet im Text der Seiten die Namen von Privatpersonen. Im Suchindex werden sie durch Platzhalter ersetzt.',
          fr: 'Repère dans le texte des pages les noms de personnes privées. Dans l’index de recherche, ils sont remplacés par des marques.',
          it: 'Individua nel testo delle pagine i nomi di persone private. Nell’indice di ricerca vengono sostituiti da segnaposto.',
          en: 'Finds the names of private individuals in the text of the pages. In the search index they are replaced by placeholders.'
        },
        parts: [
          {
            label: { de: 'Modell', fr: 'Modèle', it: 'Modello', en: 'Model' },
            name: 'gheim-ch-560m',
            href: 'https://huggingface.co/joelbarmettler/gheim-ch-560m',
            license: 'Apache-2.0'
          },
          {
            label: { de: 'Datensatz', fr: 'Jeu de données', it: 'Dataset', en: 'Dataset' },
            name: 'gheim-ch-pii-212k',
            href: 'https://huggingface.co/datasets/joelbarmettler/gheim-ch-pii-212k',
            license: 'CC BY 4.0'
          },
          {
            label: {
              de: 'Grundmodell',
              fr: 'Modèle de base',
              it: 'Modello di base',
              en: 'Base model'
            },
            name: 'XLM-RoBERTa large (Facebook AI)',
            href: 'https://huggingface.co/FacebookAI/xlm-roberta-large',
            license: 'MIT'
          }
        ]
      },
      {
        name: 'LightOnOCR-3-4B',
        href: 'https://huggingface.co/lightonai/LightOnOCR-3-4B',
        by: 'LightOn',
        license: 'Apache-2.0',
        use: {
          de: 'Erkennt den Text von Seiten ohne Textebene, etwa von eingescannten Seiten.',
          fr: 'Reconnaît le texte des pages sans couche de texte, par exemple des pages numérisées.',
          it: 'Riconosce il testo delle pagine senza livello di testo, per esempio delle pagine scansionate.',
          en: 'Recognises the text of pages without a text layer, such as scanned pages.'
        },
        parts: [
          {
            label: { de: 'Betrieben mit', fr: 'Exécuté avec', it: 'Eseguito con', en: 'Run with' },
            name: 'vLLM',
            href: 'https://github.com/vllm-project/vllm',
            license: 'Apache-2.0'
          }
        ]
      },
      {
        name: 'PyMuPDF',
        href: 'https://github.com/pymupdf/pymupdf',
        by: 'Artifex',
        license: 'AGPL-3.0',
        use: {
          de: 'Liest die PDF-Dateien: die Textebene jeder Seite und die Seitenbilder für die Einordnung und die Texterkennung.',
          fr: 'Lit les fichiers PDF : la couche de texte de chaque page et les images des pages pour la classification et la reconnaissance de texte.',
          it: 'Legge i file PDF: il livello di testo di ogni pagina e le immagini delle pagine per la classificazione e il riconoscimento del testo.',
          en: 'Reads the PDF files: the text layer of every page and the page images for classification and text recognition.'
        }
      },
      {
        name: {
          de: 'Sprachmodell',
          fr: 'Modèle de langage',
          it: 'Modello linguistico',
          en: 'Language model'
        },
        href: 'https://openai.com/api/',
        by: 'OpenAI',
        license: {
          de: 'Kommerzieller Dienst',
          fr: 'Service commercial',
          it: 'Servizio commerciale',
          en: 'Commercial service'
        },
        use: {
          de: 'Ordnet die Dokumente ein: Dokumentart, Teile, Gremium und Jahr. Die Anfragen gehen über die OpenAI-API; hochgeladene Seitenbilder werden nach der Auswertung beim Anbieter gelöscht.',
          fr: 'Classe les documents : type de document, parties, organe et année. Les requêtes passent par l’API d’OpenAI ; les images de pages envoyées sont effacées chez le fournisseur après le traitement.',
          it: 'Classifica i documenti: tipo di documento, parti, organo e anno. Le richieste passano per l’API di OpenAI; le immagini delle pagine inviate vengono cancellate presso il fornitore dopo l’elaborazione.',
          en: 'Classifies the documents: document type, parts, body and year. The requests go through the OpenAI API; uploaded page images are deleted at the provider once they have been processed.'
        }
      }
    ]
  },
  {
    title: {
      de: 'Karte und Gemeinden',
      fr: 'Carte et communes',
      it: 'Mappa e comuni',
      en: 'Map and municipalities'
    },
    credits: [
      {
        name: 'swissBOUNDARIES3D',
        href: 'https://www.swisstopo.admin.ch/en/landscape-model-swissboundaries3d',
        by: {
          de: 'Bundesamt für Landestopografie swisstopo',
          fr: 'Office fédéral de topographie swisstopo',
          it: 'Ufficio federale di topografia swisstopo',
          en: 'Federal Office of Topography swisstopo'
        },
        license: {
          de: 'Freie Geodaten, © swisstopo',
          fr: 'Géodonnées libres, © swisstopo',
          it: 'Geodati liberi, © swisstopo',
          en: 'Free geodata, © swisstopo'
        },
        use: {
          de: 'Die Grenzen der Gemeinden und Kantone auf der Karte (Stand 1. Januar 2026).',
          fr: 'Les limites des communes et des cantons sur la carte (état au 1er janvier 2026).',
          it: 'I confini dei comuni e dei cantoni sulla mappa (stato al 1° gennaio 2026).',
          en: 'The boundaries of the municipalities and cantons on the map (as of 1 January 2026).'
        },
        parts: [
          {
            label: {
              de: 'Aufbereitet mit',
              fr: 'Préparé avec',
              it: 'Preparato con',
              en: 'Prepared with'
            },
            name: 'swiss-maps 4.7.0 (Interactive Things)',
            href: 'https://github.com/interactivethings/swiss-maps',
            license: 'BSD-3-Clause'
          }
        ]
      },
      {
        name: {
          de: 'Amtliches Gemeindeverzeichnis der Schweiz',
          fr: 'Répertoire officiel des communes de Suisse',
          it: 'Elenco ufficiale dei Comuni della Svizzera',
          en: 'Swiss official commune register'
        },
        href: 'https://www.agvchapp.bfs.admin.ch',
        by: {
          de: 'Bundesamt für Statistik (BFS)',
          fr: 'Office fédéral de la statistique (OFS)',
          it: 'Ufficio federale di statistica (UST)',
          en: 'Federal Statistical Office (FSO)'
        },
        license: {
          de: 'Freie Nutzung, Quellenangabe Pflicht',
          fr: 'Utilisation libre, indication de la source obligatoire',
          it: 'Libero utilizzo, indicazione della fonte obbligatoria',
          en: 'Free use, citing the source required'
        },
        use: {
          de: 'Die Liste aller Gemeinden mit ihren Nummern, Stand 1. Januar 2026.',
          fr: 'La liste de toutes les communes avec leur numéro, état au 1er janvier 2026.',
          it: 'L’elenco di tutti i comuni con il loro numero, stato al 1° gennaio 2026.',
          en: 'The list of all municipalities with their numbers, as of 1 January 2026.'
        }
      }
    ]
  }
];

export const errorPage = {
  de: {
    notFoundTitle: 'Seite nicht gefunden',
    notFound: 'Unter dieser Adresse gibt es keine Seite und keine Gemeinde im Archiv.',
    errorTitle: 'Archiv nicht erreichbar',
    status: 'Fehler',
    home: 'Zur Startseite'
  },
  fr: {
    notFoundTitle: 'Page introuvable',
    notFound: 'Il n’y a ni page ni commune des archives à cette adresse.',
    errorTitle: 'Archives indisponibles',
    status: 'Erreur',
    home: 'Vers la page d’accueil'
  },
  it: {
    notFoundTitle: 'Pagina non trovata',
    notFound: 'A questo indirizzo non c’è né una pagina né un comune dell’archivio.',
    errorTitle: 'Archivio non raggiungibile',
    status: 'Errore',
    home: 'Alla pagina iniziale'
  },
  en: {
    notFoundTitle: 'Page not found',
    notFound: 'There is no page and no municipality in the archive at this address.',
    errorTitle: 'Archive not reachable',
    status: 'Error',
    home: 'To the start page'
  }
};
