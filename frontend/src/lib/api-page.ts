// The API page (/api). It says only what the server does: server/API.md and /api/openapi.json.
export const apiPage = {
  de: {
    title: 'API',
    intro:
      'OpenCommune stellt alle Daten als JSON-API bereit: nur lesend, ohne Schlüssel und ohne Konto.',
    license: 'Die Daten stehen unter CC0 1.0 und dürfen ohne Bedingungen genutzt werden.',
    caveat:
      'Titel, Gremien, Datumsangaben und Teile stammen aus einer automatischen Klassifikation, die noch keine Person geprüft hat. Namen von Privatpersonen erscheinen als [name].',
    openapi: 'OpenAPI-Beschreibung (JSON)',
    mcpTitle: 'Für KI-Assistenten (MCP)',
    mcp: 'KI-Assistenten können dieselben Daten über MCP nutzen, unter {url} (Streamable HTTP). Die Werkzeuge heissen search_documents, get_document und list_communes.',
    mcpConfig: 'Eintrag für die MCP-Konfiguration eines Assistenten:',
    mcpConnector:
      'In Claude oder ChatGPT lässt sich die Adresse als benutzerdefinierter Connector hinzufügen.',
    copy: 'Kopieren',
    copied: 'Kopiert',
    referenceTitle: 'Referenz',
    referenceNote:
      'Alle Endpunkte mit ihren Parametern und Antworten. Anfragen aus der Referenz gehen direkt an diese Website.',
    loading: 'Die Referenz wird geladen …',
    failed: 'Die Referenz konnte nicht geladen werden.'
  },
  fr: {
    title: 'API',
    intro:
      'OpenCommune met toutes ses données à disposition sous forme d’API JSON : en lecture seule, sans clé ni compte.',
    license: 'Les données sont publiées sous CC0 1.0 et peuvent être utilisées sans condition.',
    caveat:
      'Les titres, organes, dates et parties proviennent d’une classification automatique qu’aucune personne n’a encore vérifiée. Les noms de personnes privées apparaissent sous la forme [name].',
    openapi: 'Description OpenAPI (JSON)',
    mcpTitle: 'Pour les assistants IA (MCP)',
    mcp: 'Les assistants IA peuvent utiliser les mêmes données via MCP, à l’adresse {url} (HTTP streamable). Les outils s’appellent search_documents, get_document et list_communes.',
    mcpConfig: 'Entrée pour la configuration MCP d’un assistant :',
    mcpConnector:
      'Dans Claude ou ChatGPT, l’adresse peut être ajoutée comme connecteur personnalisé.',
    copy: 'Copier',
    copied: 'Copié',
    referenceTitle: 'Référence',
    referenceNote:
      'Tous les points d’accès avec leurs paramètres et leurs réponses. Les requêtes envoyées depuis la référence vont directement à ce site.',
    loading: 'Chargement de la référence …',
    failed: 'La référence n’a pas pu être chargée.'
  },
  it: {
    title: 'API',
    intro:
      'OpenCommune mette a disposizione tutti i dati come API JSON: in sola lettura, senza chiave e senza account.',
    license: 'I dati sono pubblicati con licenza CC0 1.0 e possono essere usati senza condizioni.',
    caveat:
      'Titoli, organi, date e parti provengono da una classificazione automatica che nessuna persona ha ancora verificato. I nomi di persone private appaiono come [name].',
    openapi: 'Descrizione OpenAPI (JSON)',
    mcpTitle: 'Per assistenti IA (MCP)',
    mcp: 'Gli assistenti IA possono usare gli stessi dati tramite MCP, all’indirizzo {url} (HTTP streamable). Gli strumenti si chiamano search_documents, get_document e list_communes.',
    mcpConfig: 'Voce per la configurazione MCP di un assistente:',
    mcpConnector:
      'In Claude o ChatGPT l’indirizzo si può aggiungere come connettore personalizzato.',
    copy: 'Copia',
    copied: 'Copiato',
    referenceTitle: 'Riferimento',
    referenceNote:
      'Tutti gli endpoint con i loro parametri e le risposte. Le richieste inviate dal riferimento vanno direttamente a questo sito.',
    loading: 'Caricamento del riferimento …',
    failed: 'Non è stato possibile caricare il riferimento.'
  }
};
