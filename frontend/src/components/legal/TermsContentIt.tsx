import { Link } from "@/i18n/navigation";

export default function TermsContentIt() {
  return (
    <>
      <section>
        <h2>1. Descrizione del servizio</h2>
        <p>
          Expensum è un servizio di tracciamento e analisi delle spese personali accessibile tramite bot Telegram e web app. Il servizio permette di registrare spese, entrate e abbonamenti, generare report e consultare dashboard analitiche.
        </p>
        <p>
          Il servizio è fornito da <strong>Michele Pinotti</strong>, Italia — <a href="mailto:expensum.finance@gmail.com">expensum.finance@gmail.com</a>.
        </p>
      </section>

      <section>
        <h2>2. Accettazione dei termini</h2>
        <p>
          L&apos;utilizzo di Expensum implica l&apos;accettazione integrale dei presenti Termini di Servizio e della <Link href="/privacy">Privacy Policy</Link>. Se non accetti queste condizioni, non utilizzare il servizio.
        </p>
        <p>
          L&apos;utente deve avere almeno 18 anni per utilizzare Expensum (D.Lgs. 101/2018 — capacità contrattuale richiesta per l&apos;accesso al piano Pro).
        </p>
      </section>

      <section>
        <h2>3. Piani e accesso al servizio</h2>

        <h3>Piano Free</h3>
        <ul>
          <li>Registrazione spese via testo</li>
          <li>Categorie personalizzabili</li>
          <li>Report mensile via Telegram</li>
          <li>Limite di token mensile per prevenire abusi automatizzati</li>
          <li>Accesso alla web app con funzionalità base</li>
        </ul>

        <h3>Piano Pro (a pagamento)</h3>
        <ul>
          <li>Tutte le funzionalità Free</li>
          <li>Registrazione spese via foto scontrino e messaggi vocali</li>
          <li>Analytics avanzata (grafici, previsioni, storico esteso)</li>
          <li>Rilevamento automatico abbonamenti ricorrenti</li>
          <li>Chat conversazionale AI (&quot;Moneo&quot;)</li>
          <li>Limite di token mensile significativamente più elevato</li>
        </ul>

        <p>
          Il prezzo del piano Pro è indicato sulla pagina <Link href="/#prezzi">Prezzi</Link> e può essere aggiornato con preavviso di 30 giorni agli utenti attivi.
        </p>
      </section>

      <section>
        <h2>4. Account utente</h2>
        <p>
          L&apos;utente è responsabile della sicurezza delle proprie credenziali di accesso. In caso di accesso non autorizzato, è tenuto a notificarlo tempestivamente a <a href="mailto:expensum.finance@gmail.com">expensum.finance@gmail.com</a>.
        </p>
        <p>
          Ciascun utente può creare un solo account. La creazione di account multipli per aggirare i limiti del piano Free è vietata.
        </p>
      </section>

      <section>
        <h2>5. Uso accettabile</h2>
        <p>È vietato utilizzare Expensum per:</p>
        <ul>
          <li>Automatizzare l&apos;invio massivo di messaggi al bot (spam, scraping).</li>
          <li>Testare vulnerabilità o effettuare tentativi di accesso non autorizzati.</li>
          <li>Inserire dati falsi o fuorvianti a scopo di test sistematico che impatta il servizio.</li>
          <li>Rivendere o sublicenziare l&apos;accesso al servizio a terzi.</li>
          <li>Qualsiasi utilizzo contrario alla legge italiana o europea applicabile.</li>
        </ul>
      </section>

      <section>
        <h2>6. Natura del servizio — non è consulenza finanziaria</h2>
        <p>
          <strong>Expensum è uno strumento di tracciamento e organizzazione delle spese personali. Non fornisce consulenza finanziaria, fiscale, di investimento o legale.</strong>
        </p>
        <p>
          Le analisi, i report, le previsioni e le risposte generate da Moneo (AI) sono prodotte automaticamente e potrebbero contenere errori. L&apos;utente è l&apos;unico responsabile delle decisioni finanziarie prese sulla base delle informazioni visualizzate nel servizio. Per decisioni finanziarie rilevanti, consulta sempre un professionista abilitato.
        </p>
      </section>

      <section>
        <h2>7. Accuratezza dei dati AI</h2>
        <p>
          I modelli AI utilizzati per il parsing delle spese (Mistral AI) e la trascrizione vocale (Google Gemini) possono commettere errori: importi letti male da scontrini poco leggibili, categorizzazioni errate, trascrizioni imprecise.
        </p>
        <p>
          L&apos;utente è invitato a verificare i dati inseriti, specialmente prima di consultare report per decisioni importanti. Ogni spesa può essere corretta manualmente in qualsiasi momento.
        </p>
      </section>

      <section>
        <h2>8. Disponibilità del servizio</h2>
        <p>
          Expensum si impegna a garantire la massima disponibilità del servizio, ma non offre garanzie di uptime minimo (SLA) per gli utenti del piano Free. Il servizio può essere interrotto temporaneamente per manutenzione, aggiornamenti o cause di forza maggiore.
        </p>
        <p>
          In caso di interruzione prolungata (oltre 24 ore), gli utenti attivi saranno notificati tramite canale Telegram ufficiale.
        </p>
      </section>

      <section>
        <h2>9. Proprietà intellettuale</h2>
        <p>
          Il codice sorgente, il design, il marchio Expensum e il personaggio Moneo sono di proprietà esclusiva di Michele Pinotti. I dati finanziari inseriti dall&apos;utente rimangono di proprietà dell&apos;utente.
        </p>
        <p>
          L&apos;utente concede a Expensum una licenza limitata, non esclusiva e non trasferibile, di trattare i dati inseriti al solo fine di erogare il servizio.
        </p>
      </section>

      <section>
        <h2>10. Sospensione e cancellazione dell&apos;account</h2>
        <p>
          Expensum si riserva il diritto di sospendere o cancellare l&apos;account di un utente in caso di violazione dei presenti Termini, previo avviso via Telegram o email (eccetto in caso di abusi gravi, dove la sospensione può essere immediata).
        </p>
        <p>
          L&apos;utente può cancellare il proprio account in qualsiasi momento dalla sezione <strong>Impostazioni → Privacy e dati → Elimina account</strong>. Tutti i dati personali saranno eliminati entro 30 giorni, ad eccezione di quanto necessario per adempimenti legali.
        </p>
      </section>

      <section>
        <h2>11. Limitazione di responsabilità</h2>
        <p>
          Nei limiti consentiti dalla legge applicabile, Michele Pinotti non è responsabile per:
        </p>
        <ul>
          <li>Perdita di dati dovuta a cause di forza maggiore o guasti hardware.</li>
          <li>Decisioni finanziarie prese sulla base dei dati o delle analisi AI di Expensum.</li>
          <li>Interruzioni del servizio di Telegram, Mistral AI, Google o altri provider terzi.</li>
          <li>Danni indiretti, consequenziali o di lucro cessante.</li>
        </ul>
        <p>
          La responsabilità massima di Expensum nei confronti di un utente Pro è limitata all&apos;importo pagato negli ultimi 12 mesi.
        </p>
      </section>

      <section>
        <h2>11b. Diritto di recesso (consumatori UE)</h2>
        <p>
          Ai sensi della Direttiva 2011/83/UE sui diritti dei consumatori, l&apos;utente che
          acquista il piano Pro ha diritto di recedere dal contratto entro <strong>14 giorni</strong>
          dalla data di attivazione, senza necessità di fornire motivazioni.
        </p>
        <p>
          Il diritto di recesso decade se l&apos;utente ha espressamente richiesto l&apos;inizio
          dell&apos;esecuzione del servizio durante il periodo di recesso e il servizio è stato
          completamente eseguito (Art. 59(a) Dir. 2011/83/UE). Poiché il piano Pro è un servizio
          digitale con accesso immediato, <strong>accettando l&apos;attivazione istantanea
          l&apos;utente acconsente all&apos;inizio dell&apos;esecuzione e riconosce la perdita
          del diritto di recesso al momento della completa esecuzione.</strong>
        </p>
        <p>
          Per esercitare il diritto di recesso prima della scadenza dei 14 giorni, scrivi a
          <a href="mailto:expensum.finance@gmail.com"> expensum.finance@gmail.com</a> con
          oggetto &quot;Recesso piano Pro&quot;. Il rimborso sarà erogato entro 14 giorni.
        </p>
      </section>

      <section>
        <h2>12. Modifiche ai termini</h2>
        <p>
          Expensum si riserva il diritto di modificare i presenti Termini. Le modifiche saranno
          comunicate con almeno <strong>15 giorni di preavviso</strong> tramite notifica Telegram
          o email. Per modifiche sostanziali che incidano sui diritti dell&apos;utente o
          amplino le finalità di trattamento dei dati, sarà richiesta <strong>accettazione
          esplicita</strong> prima di continuare a utilizzare il servizio. L&apos;uso continuato
          del servizio dopo il preavviso costituisce accettazione solo per le modifiche di natura
          non sostanziale (es. correzioni redazionali, chiarimenti, aggiornamenti normativi che
          non incidono sui diritti dell&apos;utente).
        </p>
      </section>

      <section>
        <h2>13. Legge applicabile e foro competente</h2>
        <p>
          I presenti Termini sono disciplinati dalla legge italiana. Per qualsiasi controversia che non sia stata risolta amichevolmente, il foro competente è quello del luogo di residenza del consumatore (utente). Per controversie con utenti non consumatori, il foro è quello di Milano.
        </p>
        <p>
          Gli utenti residenti nell&apos;UE hanno il diritto di ricorrere alla piattaforma ODR (Online Dispute Resolution) della Commissione Europea: <a href="https://ec.europa.eu/consumers/odr" target="_blank" rel="noopener noreferrer">ec.europa.eu/consumers/odr</a>.
        </p>
      </section>

      <section>
        <h2>14. Contatti</h2>
        <p>
          Per qualsiasi domanda sui presenti Termini: <a href="mailto:expensum.finance@gmail.com">expensum.finance@gmail.com</a>
        </p>
      </section>
    </>
  );
}
