//! The pages search engines and AI assistants read. The front end renders in the browser, so the
//! server puts each page's facts into the HTML it sends anyway: title, description, canonical and
//! language links, schema.org data and a short fact sheet (`<main id="oc-facts">`). A visitor with
//! JavaScript never sees the fact sheet: an inline script hides it, the app removes it on start,
//! shows the same facts and writes its own titles into the same `<title>`. Every visitor receives
//! the same HTML.

use std::path::Path;
use std::sync::Arc;

/// The site's languages; the first is the default.
#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub enum Lang {
    De,
    Fr,
    It,
}

impl Lang {
    pub const ALL: [Lang; 3] = [Lang::De, Lang::Fr, Lang::It];

    pub fn code(self) -> &'static str {
        match self {
            Lang::De => "de",
            Lang::Fr => "fr",
            Lang::It => "it",
        }
    }

    pub fn words(self) -> &'static Words {
        match self {
            Lang::De => &DE,
            Lang::Fr => &FR,
            Lang::It => &IT,
        }
    }

    /// A count with the thousands separator of the language in Switzerland.
    pub fn number(self, n: i64) -> String {
        let sep = if self == Lang::Fr { "\u{202f}" } else { "’" };
        let digits = n.unsigned_abs().to_string();
        let mut out = String::new();
        for (i, c) in digits.chars().enumerate() {
            if i > 0 && (digits.len() - i).is_multiple_of(3) {
                out.push_str(sep);
            }
            out.push(c);
        }
        if n < 0 { format!("-{out}") } else { out }
    }
}

/// The fixed texts of the pages, per language. `{x}` marks a value filled in by the page.
pub struct Words {
    pub site: &'static str,
    pub totals: &'static str,
    pub with_documents: &'static str,
    pub commune_line: &'static str,
    pub by_year: &'static str,
    pub no_year: &'static str,
    pub untitled: &'static str,
    pub recent: &'static str,
    pub website: &'static str,
    pub about: &'static str,
    pub about_text: &'static str,
    pub privacy: &'static str,
    pub privacy_text: &'static str,
    pub search: &'static str,
}

const DE: Words = Words {
    site: "Offenes Archiv der Dokumente Schweizer Gemeinden: Protokolle, Beschlüsse, Budgets, \
           Rechnungen und weitere Unterlagen von Gemeindeversammlungen, Parlamenten und \
           Gemeinderäten, mit Links zu den Originalen.",
    totals: "{documents} Dokumente aus {communes} Gemeinden, verlinkt auf die Originale. Sie \
             sind automatisch nach Titel, Gremium und Abschnitten eingeordnet; diese Einordnung \
             hat noch niemand geprüft.",
    with_documents: "Gemeinden mit Dokumenten",
    commune_line: "{name} ({canton}): {documents} Dokumente im offenen Archiv OpenCommune.",
    by_year: "Dokumente nach Jahr",
    no_year: "ohne Jahr",
    untitled: "Dokument ohne Titel",
    recent: "Neueste Dokumente",
    website: "Website der Gemeinde",
    about: "Über OpenCommune",
    about_text: "OpenCommune sammelt die öffentlichen Dokumente der Schweizer Gemeinden von ihren \
                 Websites, ordnet sie automatisch nach Art, Gremium und Abschnitten ein und \
                 verlinkt sie auf die Originale. Die Einträge sind offene Daten (CC0).",
    privacy: "Datenschutz",
    privacy_text: "Keine Cookies, nichts von Dritten; die Nutzungsstatistik zählt Aufrufe ohne \
                   IP-Adressen und Suchbegriffe. Das Archiv nennt keine Privatpersonen: Dokumente \
                   tragen feste Bezeichnungen, Einbürgerungsunterlagen werden nicht aufgeführt.",
    search: "Suche",
};

const FR: Words = Words {
    site: "Archive ouverte des documents des communes suisses : procès-verbaux, décisions, \
           budgets, comptes et autres documents des assemblées communales, conseils généraux et \
           conseils communaux, avec des liens vers les originaux.",
    totals: "{documents} documents de {communes} communes, liés aux originaux. Ils sont \
             classés automatiquement par titre, organe et sections ; personne n’a encore \
             vérifié ce classement.",
    with_documents: "Communes avec des documents",
    commune_line: "{name} ({canton}) : {documents} documents dans l’archive ouverte OpenCommune.",
    by_year: "Documents par année",
    no_year: "sans année",
    untitled: "Document sans titre",
    recent: "Documents récents",
    website: "Site de la commune",
    about: "À propos d’OpenCommune",
    about_text: "OpenCommune rassemble les documents publics des communes suisses sur leurs \
                 sites, les classe automatiquement par type, organe et sections et renvoie aux \
                 originaux. Les entrées sont des données ouvertes (CC0).",
    privacy: "Protection des données",
    privacy_text: "Pas de cookies, rien de tiers ; les statistiques comptent les accès sans \
                   adresses IP ni termes de recherche. L’archive ne nomme aucune personne privée : \
                   les documents portent des intitulés fixes et les documents de naturalisation ne \
                   sont pas répertoriés.",
    search: "Recherche",
};

const IT: Words = Words {
    site: "Archivio aperto dei documenti dei comuni svizzeri: verbali, decisioni, preventivi, \
           consuntivi e altri documenti delle assemblee comunali, dei consigli comunali e dei \
           municipi, con link agli originali.",
    totals: "{documents} documenti da {communes} comuni, con link agli originali. Sono \
             classificati automaticamente per titolo, organo e sezioni; nessuno ha ancora \
             verificato questa classificazione.",
    with_documents: "Comuni con documenti",
    commune_line: "{name} ({canton}): {documents} documenti nell’archivio aperto OpenCommune.",
    by_year: "Documenti per anno",
    no_year: "senza anno",
    untitled: "Documento senza titolo",
    recent: "Documenti recenti",
    website: "Sito del comune",
    about: "Informazioni su OpenCommune",
    about_text: "OpenCommune raccoglie i documenti pubblici dei comuni svizzeri dai loro siti, li \
                 classifica automaticamente per tipo, organo e sezioni e rimanda agli originali. \
                 Le voci sono dati aperti (CC0).",
    privacy: "Protezione dei dati",
    privacy_text: "Nessun cookie, nulla da terzi; le statistiche contano gli accessi senza \
                   indirizzi IP né termini di ricerca. L’archivio non nomina persone private: i \
                   documenti portano denominazioni fisse e i documenti di naturalizzazione non \
                   sono elencati.",
    search: "Ricerca",
};

/// One page as the server sends it: what goes into `<head>` and the fact sheet.
pub struct Page {
    pub lang: Lang,
    /// The path after the language, `""` for the start page, e.g. `/gemeinden/261`.
    pub path: String,
    pub title: String,
    pub description: String,
    /// schema.org JSON-LD, when the page has some.
    pub json_ld: Option<serde_json::Value>,
    /// The fact sheet's HTML, already escaped.
    pub facts: String,
    /// Search result pages are never indexed.
    pub noindex: bool,
}

/// The page shell when the front end is not built: the pages carry only their facts.
const NO_SHELL: &str = "<!doctype html><html lang=\"de\"><head></head><body></body></html>";

/// What the page renderer needs: the public address, whether search engines may index the site,
/// and where the front end's `index.html` is.
#[derive(Clone)]
pub struct Site {
    pub public_url: String,
    pub indexing: bool,
    shell: Arc<Path>,
}

impl Site {
    pub fn new(public_url: &str, indexing: bool, static_dir: &Path) -> Self {
        Site {
            public_url: public_url.trim_end_matches('/').to_string(),
            indexing,
            shell: static_dir.join("index.html").into(),
        }
    }

    /// The front end's `index.html`, read for every page: it names the build's script files, so a
    /// newly deployed front end must be picked up without a restart.
    pub async fn shell(&self) -> String {
        tokio::fs::read_to_string(&*self.shell)
            .await
            .unwrap_or_else(|_| NO_SHELL.to_string())
    }

    pub fn url(&self, lang: Lang, path: &str) -> String {
        format!("{}/{}{}", self.public_url, lang.code(), path)
    }

    /// `shell` with the page's head tags and fact sheet.
    pub fn render(&self, shell: &str, page: &Page) -> String {
        let mut head = format!(
            "<title>{}</title>\n<meta name=\"description\" content=\"{}\">\n\
             <link rel=\"canonical\" href=\"{}\">\n",
            escape(&page.title),
            escape(&page.description),
            escape(&self.url(page.lang, &page.path)),
        );
        for lang in Lang::ALL {
            head.push_str(&format!(
                "<link rel=\"alternate\" hreflang=\"{}\" href=\"{}\">\n",
                lang.code(),
                escape(&self.url(lang, &page.path))
            ));
        }
        head.push_str(&format!(
            "<link rel=\"alternate\" hreflang=\"x-default\" href=\"{}\">\n",
            escape(&self.url(Lang::De, &page.path))
        ));
        if page.noindex {
            head.push_str("<meta name=\"robots\" content=\"noindex\">\n");
        }
        if let Some(data) = &page.json_ld {
            // `</` would end the script element early
            let json = data.to_string().replace("</", "<\\/");
            head.push_str(&format!(
                "<script type=\"application/ld+json\">{json}</script>\n"
            ));
        }
        head.push_str(
            "<script>document.documentElement.classList.add('js')</script>\n\
             <style>.js #oc-facts{display:none}</style>\n",
        );
        let body = format!("<main id=\"oc-facts\">{}</main>", page.facts);
        let html = shell.replacen(
            "<html lang=\"de\">",
            &format!("<html lang=\"{}\">", page.lang.code()),
            1,
        );
        inject(&html, &head, &body)
    }
}

/// Puts `head` before `</head>` and `body` right after the opening `<body>` tag.
fn inject(html: &str, head: &str, body: &str) -> String {
    let mut out = String::with_capacity(html.len() + head.len() + body.len());
    let (before_head, after_head) = match html.find("</head>") {
        Some(i) => html.split_at(i),
        None => ("", html),
    };
    out.push_str(before_head);
    out.push_str(head);
    match after_head
        .find("<body")
        .and_then(|i| after_head[i..].find('>').map(|j| i + j + 1))
    {
        Some(i) => {
            out.push_str(&after_head[..i]);
            out.push_str(body);
            out.push_str(&after_head[i..]);
        }
        None => {
            out.push_str(after_head);
            out.push_str(body);
        }
    }
    out
}

/// Text for HTML element content and attribute values.
pub fn escape(text: &str) -> String {
    let mut out = String::with_capacity(text.len());
    for c in text.chars() {
        match c {
            '&' => out.push_str("&amp;"),
            '<' => out.push_str("&lt;"),
            '>' => out.push_str("&gt;"),
            '"' => out.push_str("&quot;"),
            '\'' => out.push_str("&#39;"),
            _ => out.push(c),
        }
    }
    out
}

/// `YYYY-MM-DD` as `DD.MM.YYYY`; anything else as it is.
pub fn date(iso: &str) -> String {
    match (iso.get(0..4), iso.get(5..7), iso.get(8..10)) {
        (Some(y), Some(m), Some(d)) if iso.len() >= 10 => format!("{d}.{m}.{y}"),
        _ => iso.to_string(),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn numbers_dates_and_escaping() {
        assert_eq!(Lang::De.number(360723), "360’723");
        assert_eq!(Lang::Fr.number(1000), "1\u{202f}000");
        assert_eq!(Lang::It.number(999), "999");
        assert_eq!(date("2026-03-14"), "14.03.2026");
        assert_eq!(
            escape("<a href=\"x\">&'"),
            "&lt;a href=&quot;x&quot;&gt;&amp;&#39;"
        );
    }

    #[test]
    fn head_and_facts_go_into_the_shell() {
        let html = inject(
            "<html lang=\"de\"><head><meta></head><body data-x=\"1\"><div></div></body></html>",
            "<title>t</title>",
            "<main>f</main>",
        );
        assert_eq!(
            html,
            "<html lang=\"de\"><head><meta><title>t</title></head><body data-x=\"1\"><main>f</main><div></div></body></html>"
        );
    }
}
