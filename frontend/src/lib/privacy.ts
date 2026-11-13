// The privacy page (/datenschutz). It describes what the server and the site actually do:
// server/src/usage.rs for the statistics, server/src/site.rs and the front end for the rest.
type Section = { title: string; paragraphs: string[] };
export const privacy: Record<
  'de' | 'fr' | 'it',
  { title: string; updated: string; intro: string; sections: Section[]; contact: string }
> = {
  de: {
    title: 'Datenschutz',
    updated: 'Stand: 12. November 2026',
    intro:
      'Diese Seite erklärt, welche Daten OpenCommune beim Besuch der Website, bei der Nutzung der API und des MCP-Servers verarbeitet, und wie mit Personen umgegangen wird, die in den Dokumenten der Gemeinden vorkommen.',
    sections: [
      {
        title: 'Verantwortlich',
        paragraphs: [
          'OpenCommune ist ein Projekt von David Zollikofer. Fragen und Anliegen zum Datenschutz nehmen wir per E-Mail entgegen.'
        ]
      },
      {
        title: 'Besuch der Website',
        paragraphs: [
          'Die Website setzt keine Cookies, verwendet keine Analyse- oder Werbedienste und lädt nichts von Dritten nach; auch die Schrift wird von unserem eigenen Server geladen.',
          'Für die Nutzungsstatistik zählt der Server Aufrufe pro Tag, Seitentyp und Antwortstatus. IP-Adressen, vollständige Adressen der aufgerufenen Seiten und Suchbegriffe werden nicht gespeichert. Die Zahl der Besuchenden pro Tag wird aus einem Prüfwert von IP-Adresse und Browserkennung geschätzt, der mit einem täglich wechselnden Schlüssel gebildet wird; der Schlüssel wird am Folgetag gelöscht, sodass niemand über Tage hinweg wiedererkannt werden kann. Wer «Do Not Track» oder «Global Privacy Control» sendet, fliesst nicht in diese Schätzung ein. Die Statistik wird nach 30 Tagen gelöscht.',
          'Die Protokolle des Servers enthalten nur den Seitentyp einer Anfrage, keine Adressen und keine Suchbegriffe.'
        ]
      },
      {
        title: 'API und MCP-Server',
        paragraphs: [
          'Anfragen an die API und an den MCP-Server werden wie Seitenaufrufe nur gezählt, pro Tag und Abfrage; Suchbegriffe werden nicht gespeichert, nur ob eine Suche Treffer hatte.',
          'Wer OpenCommune über einen KI-Assistenten wie Claude oder ChatGPT nutzt, gibt seine Fragen dort ein. Für diese Eingaben gilt die Datenschutzerklärung des jeweiligen Anbieters; OpenCommune erhält nur die Abfrage, die der Assistent an den MCP-Server schickt.'
        ]
      },
      {
        title: 'Personen in den Dokumenten',
        paragraphs: [
          'Das Archiv beruht auf öffentlich zugänglichen Dokumenten der Gemeinden und ihrer Parlamente. In den erfassten Entscheiden werden die Namen von Privatpersonen durch [Person] ersetzt; Amtsträgerinnen und Amtsträger in ihrer amtlichen Funktion bleiben genannt. Entscheide zu Einbürgerungen, Sozialhilfe, Erwachsenenschutz, Gesundheit und erkennbaren Personalfragen werden nicht veröffentlicht.',
          'Die Dokumentlisten zeigen nur neutrale Bezeichnungen und verlinken auf das Original bei der Gemeinde. Dokumente, deren Titel oder Adresse auf eine Einbürgerung hinweist, werden nicht aufgeführt.',
          'Wer eine Angabe zu einer Person findet, die nicht hierher gehört, kann uns schreiben. Wir prüfen jede Meldung und entfernen die Angabe, wo nötig.'
        ]
      },
      {
        title: 'Ihre Rechte',
        paragraphs: [
          'Sie können nach dem Schweizer Datenschutzgesetz Auskunft über Daten zu Ihrer Person verlangen und deren Berichtigung oder Löschung beantragen. Eine E-Mail genügt.'
        ]
      },
      {
        title: 'Links zu anderen Websites',
        paragraphs: [
          'Links führen zu den Websites der Gemeinden, zu GitHub und zu Hugging Face. Für diese Websites gelten deren eigene Datenschutzerklärungen.'
        ]
      }
    ],
    contact: 'E-Mail zum Datenschutz schreiben'
  },
  fr: {
    title: 'Protection des données',
    updated: 'État au 12 novembre 2026',
    intro:
      'Cette page explique quelles données OpenCommune traite lors de la visite du site, de l’utilisation de l’API et du serveur MCP, et comment sont traitées les personnes mentionnées dans les documents des communes.',
    sections: [
      {
        title: 'Responsable',
        paragraphs: [
          'OpenCommune est un projet de David Zollikofer. Les questions relatives à la protection des données peuvent nous être adressées par e-mail.'
        ]
      },
      {
        title: 'Visite du site',
        paragraphs: [
          'Le site n’utilise pas de cookies, aucun service d’analyse ou de publicité, et ne charge rien de tiers ; la police de caractères est elle aussi servie par notre propre serveur.',
          'Pour les statistiques d’utilisation, le serveur compte les accès par jour, par type de page et par statut de réponse. Les adresses IP, les adresses complètes des pages consultées et les termes de recherche ne sont pas enregistrés. Le nombre de visiteurs par jour est estimé à partir d’une empreinte de l’adresse IP et de l’identifiant du navigateur, calculée avec une clé qui change chaque jour ; la clé est effacée le lendemain, de sorte que personne ne peut être reconnu d’un jour à l’autre. Les navigateurs qui envoient « Do Not Track » ou « Global Privacy Control » ne sont pas pris en compte dans cette estimation. Les statistiques sont effacées après 30 jours.',
          'Les journaux du serveur ne contiennent que le type de page d’une requête, ni adresses ni termes de recherche.'
        ]
      },
      {
        title: 'API et serveur MCP',
        paragraphs: [
          'Comme les pages, les requêtes à l’API et au serveur MCP sont seulement comptées, par jour et par requête ; les termes de recherche ne sont pas enregistrés, seulement le fait qu’une recherche a donné des résultats.',
          'Qui utilise OpenCommune à travers un assistant IA comme Claude ou ChatGPT y saisit ses questions. La déclaration de protection des données du fournisseur concerné s’applique à ces saisies ; OpenCommune ne reçoit que la requête que l’assistant envoie au serveur MCP.'
        ]
      },
      {
        title: 'Personnes mentionnées dans les documents',
        paragraphs: [
          'L’archive repose sur des documents publics des communes et de leurs parlements. Dans les décisions saisies, les noms de personnes privées sont remplacés par [Person] ; les élues et élus et les autres titulaires d’une fonction publique restent nommés dans l’exercice de leur fonction. Les décisions concernant les naturalisations, l’aide sociale, la protection de l’adulte, la santé et des questions de personnel identifiables ne sont pas publiées.',
          'Les listes de documents n’affichent que des désignations neutres et renvoient à l’original sur le site de la commune. Les documents dont le titre ou l’adresse indique une naturalisation ne sont pas listés.',
          'Si vous trouvez une information sur une personne qui n’a pas sa place ici, écrivez-nous. Nous examinons chaque signalement et retirons l’information si nécessaire.'
        ]
      },
      {
        title: 'Vos droits',
        paragraphs: [
          'Selon la loi suisse sur la protection des données, vous pouvez demander des renseignements sur les données vous concernant et en demander la rectification ou l’effacement. Un e-mail suffit.'
        ]
      },
      {
        title: 'Liens vers d’autres sites',
        paragraphs: [
          'Des liens mènent aux sites des communes, à GitHub et à Hugging Face. Leurs propres déclarations de protection des données s’y appliquent.'
        ]
      }
    ],
    contact: 'Écrire un e-mail concernant la protection des données'
  },
  it: {
    title: 'Protezione dei dati',
    updated: 'Stato: 12 novembre 2026',
    intro:
      'Questa pagina spiega quali dati OpenCommune tratta durante la visita del sito e l’uso dell’API e del server MCP, e come vengono trattate le persone menzionate nei documenti dei comuni.',
    sections: [
      {
        title: 'Responsabile',
        paragraphs: [
          'OpenCommune è un progetto di David Zollikofer. Domande sulla protezione dei dati possono esserci inviate per e-mail.'
        ]
      },
      {
        title: 'Visita del sito',
        paragraphs: [
          'Il sito non usa cookie, nessun servizio di analisi o di pubblicità e non carica nulla da terzi; anche il carattere tipografico viene servito dal nostro server.',
          'Per le statistiche d’uso il server conta gli accessi per giorno, per tipo di pagina e per stato della risposta. Indirizzi IP, indirizzi completi delle pagine visitate e termini di ricerca non vengono registrati. Il numero di visitatori al giorno è stimato da un’impronta dell’indirizzo IP e dell’identificativo del browser, calcolata con una chiave che cambia ogni giorno; la chiave viene cancellata il giorno seguente, così nessuno può essere riconosciuto da un giorno all’altro. Chi invia «Do Not Track» o «Global Privacy Control» non viene considerato in questa stima. Le statistiche vengono cancellate dopo 30 giorni.',
          'I log del server contengono solo il tipo di pagina di una richiesta, né indirizzi né termini di ricerca.'
        ]
      },
      {
        title: 'API e server MCP',
        paragraphs: [
          'Come le pagine, le richieste all’API e al server MCP vengono solo contate, per giorno e per richiesta; i termini di ricerca non vengono registrati, solo se una ricerca ha dato risultati.',
          'Chi usa OpenCommune tramite un assistente IA come Claude o ChatGPT inserisce lì le sue domande. A questi dati si applica l’informativa sulla privacy del rispettivo fornitore; OpenCommune riceve solo la richiesta che l’assistente invia al server MCP.'
        ]
      },
      {
        title: 'Persone menzionate nei documenti',
        paragraphs: [
          'L’archivio si basa su documenti pubblici dei comuni e dei loro parlamenti. Nelle decisioni registrate i nomi di persone private sono sostituiti da [Person]; chi ricopre una carica pubblica resta nominato nell’esercizio della funzione. Le decisioni su naturalizzazioni, assistenza sociale, protezione degli adulti, salute e questioni di personale identificabili non vengono pubblicate.',
          'Gli elenchi dei documenti mostrano solo designazioni neutre e rimandano all’originale sul sito del comune. I documenti il cui titolo o indirizzo indica una naturalizzazione non vengono elencati.',
          'Se trovate un’informazione su una persona che non dovrebbe trovarsi qui, scriveteci. Esaminiamo ogni segnalazione e rimuoviamo l’informazione se necessario.'
        ]
      },
      {
        title: 'I vostri diritti',
        paragraphs: [
          'Secondo la legge svizzera sulla protezione dei dati potete chiedere informazioni sui dati che vi riguardano e chiederne la rettifica o la cancellazione. Basta un’e-mail.'
        ]
      },
      {
        title: 'Link ad altri siti',
        paragraphs: [
          'I link portano ai siti dei comuni, a GitHub e a Hugging Face. Per questi siti valgono le loro informative sulla privacy.'
        ]
      }
    ],
    contact: 'Scrivere un’e-mail sulla protezione dei dati'
  }
};
