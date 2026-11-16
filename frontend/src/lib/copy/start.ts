// Texts of the start page and the map (src/routes/[[lang=language]]/+page.svelte, Map.svelte,
// CommuneSearch.svelte). The older shared strings stay in i18n.ts.
import { fmt, type Lang } from '$lib/i18n';

export const SOURCE_URL = 'https://github.com/davidrzs/tractanda';
export const DATASET_URL = 'https://huggingface.co/datasets/davidrzs/tractanda';
export const MCP_COMMAND = 'claude mcp add --transport http tractanda https://www.tractanda.ch/mcp';
// how a private name appears in place of the name
const PERSON = '[name]';

// "1 document", "12 documents", lower case where the language writes it so
export const docs = (n: number, lang: Lang) =>
  `${fmt(n, lang)} ${n === 1 ? start[lang].documentOne : start[lang].documents}`;

export const start = {
  de: {
    pageTitle: 'Die Dokumente der Schweizer Gemeinden',
    title: 'Die Dokumente der Schweizer Gemeinden',
    lead: 'Protokolle, Beschlüsse, Budgets und Anträge aus {communes} Gemeinden, durchsuchbar an einem Ort, mit Link zum Original.',
    searchLabel: 'In allen Dokumenten suchen',
    searchPlaceholder: 'Stichwort, zum Beispiel Hallenbad',
    examples: 'Beispiele',
    exampleQueries: [
      'Tempo 30',
      'Photovoltaik',
      'Schulhaus',
      'Hallenbad',
      'Budget 2027',
      'Ortsplanung'
    ],
    machineNote: 'Titel, Daten und Arten sind maschinell gelesen und nicht von Hand geprüft.',
    documentOne: 'Dokument',
    documents: 'Dokumente',
    noDocuments: 'noch keine Dokumente',
    mapLegend: 'Je kräftiger die Farbe, desto mehr Dokumente:',
    mapPlace: 'Lage von {name}',
    mapNear: '{name} und Umgebung',
    byCount: 'Nach Anzahl Dokumente geordnet.',
    communeCount: '{n} Gemeinden',
    openTitle: 'Offen und nachvollziehbar',
    openIntro: 'Code, Daten und Methode sind frei zugänglich.',
    codeTitle: 'Quellcode',
    codeText: 'Der ganze Code auf GitHub, unter MIT-Lizenz.',
    dataTitle: 'Datensatz',
    dataText: 'Die erfassten Daten auf Hugging Face, frei unter CC0.',
    paperTitle: 'Paper',
    soon: 'bald',
    paperText: 'Wie das Archiv entsteht und wie gut die Erkennung ist.',
    apiTitle: 'JSON-API und MCP',
    apiText: 'Ohne Schlüssel. Ein KI-Assistent durchsucht das Archiv direkt.',
    mcpLabel: 'Das Archiv als MCP-Server in Claude Code einbinden:',
    copy: 'Kopieren',
    copied: 'Kopiert',
    copyLabel: 'Befehl kopieren',
    collectTitle: 'So sammeln wir',
    collectIntro: 'Von den öffentlichen Websites der Gemeinden.',
    rules: [
      'robots.txt gilt immer: Wer nicht gesammelt werden will, wird nicht gesammelt.',
      'Höchstens eine Anfrage pro Sekunde und Server.',
      `Namen von Privatpersonen werden durch ${PERSON} ersetzt.`,
      'Jeder Treffer führt zum Original. Massgeblich ist der Wortlaut der Gemeinde.',
      'Titel, Daten und Arten liest eine Maschine; niemand hat sie von Hand geprüft.',
      'Es gibt keine Rangliste und keine Bewertung von Gemeinden.'
    ],
    aboutLink: 'Mehr über das Archiv'
  },
  fr: {
    pageTitle: 'Les documents des communes suisses',
    title: 'Les documents des communes suisses',
    lead: 'Procès-verbaux, décisions, budgets et préavis de {communes} communes, consultables en un seul endroit, avec un lien vers l’original.',
    searchLabel: 'Rechercher dans tous les documents',
    searchPlaceholder: 'Mot-clé, par exemple piscine',
    examples: 'Exemples',
    exampleQueries: [
      'Zone 30',
      'Photovoltaïque',
      'Collège',
      'Piscine',
      'Budget 2027',
      'Plan d’affectation'
    ],
    machineNote:
      'Les titres, dates et types sont lus par une machine et ne sont pas vérifiés à la main.',
    documentOne: 'document',
    documents: 'documents',
    noDocuments: 'aucun document pour le moment',
    mapLegend: 'Plus la couleur est soutenue, plus il y a de documents\u00a0:',
    mapPlace: 'Situation de {name}',
    mapNear: '{name} et environs',
    byCount: 'Classées par nombre de documents.',
    communeCount: '{n} communes',
    openTitle: 'Ouvert et vérifiable',
    openIntro: 'Le code, les données et la méthode sont librement accessibles.',
    codeTitle: 'Code source',
    codeText: 'Tout le code sur GitHub, sous licence MIT.',
    dataTitle: 'Jeu de données',
    dataText: 'Les données extraites sur Hugging Face, libres sous CC0.',
    paperTitle: 'Article',
    soon: 'bientôt',
    paperText:
      'Comment les archives sont constituées et quelle est la qualité de la reconnaissance.',
    apiTitle: 'API JSON et MCP',
    apiText: 'Sans clé. Un assistant IA consulte directement les archives.',
    mcpLabel: 'Ajouter les archives comme serveur MCP dans Claude Code\u00a0:',
    copy: 'Copier',
    copied: 'Copié',
    copyLabel: 'Copier la commande',
    collectTitle: 'Comment nous collectons',
    collectIntro: 'Depuis les sites web publics des communes.',
    rules: [
      'Le fichier robots.txt s’applique toujours\u00a0: un site qui refuse la collecte n’est pas collecté.',
      'Au plus une requête par seconde et par serveur.',
      `Les noms de personnes privées sont remplacés par ${PERSON}.`,
      'Chaque résultat renvoie à l’original. Le texte de la commune fait foi.',
      'Une machine lit les titres, les dates et les types\u00a0; personne ne les a vérifiés à la main.',
      'Il n’y a ni classement ni évaluation des communes.'
    ],
    aboutLink: 'En savoir plus sur les archives'
  },
  it: {
    pageTitle: 'I documenti dei comuni svizzeri',
    title: 'I documenti dei comuni svizzeri',
    lead: 'Verbali, decisioni, preventivi e messaggi di {communes} comuni, consultabili in un unico luogo, con un link all’originale.',
    searchLabel: 'Cerca in tutti i documenti',
    searchPlaceholder: 'Parola chiave, ad esempio piscina',
    examples: 'Esempi',
    exampleQueries: [
      'Zona 30',
      'Fotovoltaico',
      'Scuola',
      'Piscina',
      'Preventivo 2027',
      'Piano regolatore'
    ],
    machineNote: 'Titoli, date e tipi sono letti da una macchina e non verificati a mano.',
    documentOne: 'documento',
    documents: 'documenti',
    noDocuments: 'nessun documento per ora',
    mapLegend: 'Più il colore è intenso, più documenti ci sono:',
    mapPlace: 'Posizione di {name}',
    mapNear: '{name} e dintorni',
    byCount: 'Ordinati per numero di documenti.',
    communeCount: '{n} comuni',
    openTitle: 'Aperto e verificabile',
    openIntro: 'Codice, dati e metodo sono liberamente accessibili.',
    codeTitle: 'Codice sorgente',
    codeText: 'Tutto il codice su GitHub, con licenza MIT.',
    dataTitle: 'Set di dati',
    dataText: 'I dati estratti su Hugging Face, liberi con CC0.',
    paperTitle: 'Articolo',
    soon: 'presto',
    paperText: 'Come nasce l’archivio e quanto è affidabile il riconoscimento.',
    apiTitle: 'API JSON e MCP',
    apiText: 'Senza chiave. Un assistente IA consulta direttamente l’archivio.',
    mcpLabel: 'Aggiungere l’archivio come server MCP in Claude Code:',
    copy: 'Copia',
    copied: 'Copiato',
    copyLabel: 'Copia il comando',
    collectTitle: 'Come raccogliamo',
    collectIntro: 'Dai siti web pubblici dei comuni.',
    rules: [
      'Il file robots.txt vale sempre: se un sito rifiuta la raccolta, non viene raccolto.',
      'Al massimo una richiesta al secondo per server.',
      `I nomi di persone private sono sostituiti da ${PERSON}.`,
      'Ogni risultato rimanda all’originale. Fa fede il testo del comune.',
      'Titoli, date e tipi sono letti da una macchina; nessuno li ha verificati a mano.',
      'Non ci sono classifiche né valutazioni dei comuni.'
    ],
    aboutLink: 'Di più sull’archivio'
  }
} satisfies Record<Lang, Record<string, string | string[]>>;
