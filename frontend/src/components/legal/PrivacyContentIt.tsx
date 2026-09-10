import { Link } from "@/i18n/navigation";
import styles from "@/app/[locale]/legal.module.css";

export default function PrivacyContentIt() {
  return (
    <>
      <section>
        <h2>1. Titolare del trattamento</h2>
        <p>
          <strong>Michele Pinotti</strong><br />
          Italia<br />
          Email: <a href="mailto:expensum.finance@gmail.com">expensum.finance@gmail.com</a>
        </p>
        <p>
          Il Titolare risponde alle richieste degli interessati entro 30 giorni dalla ricezione
          (target operativo: 24 ore), ai sensi dell&apos;Art. 12(3) GDPR.
        </p>
        <p className={styles.legalNote}>
          <strong>Responsabile della Protezione dei Dati (DPO):</strong> Non è stato designato
          un DPO in quanto il trattamento effettuato da Expensum non rientra nei casi di
          designazione obbligatoria di cui all&apos;Art. 37 GDPR (non si tratta di autorità
          pubblica, né di trattamento su larga scala di categorie speciali di dati, né di
          monitoraggio sistematico su larga scala).
        </p>
      </section>

      <section>
        <h2>2. Dati trattati e finalità</h2>
        <p>
          Il servizio è riservato a utenti <strong>maggiorenni (18 anni o più)</strong>, verificato
          tramite attestazione esplicita richiesta alla registrazione. Non raccogliamo
          consapevolmente dati di minori (Art. 8 GDPR; D.Lgs. 101/2018, capacità contrattuale).
        </p>

        <h3>2.1 Dati forniti direttamente dall&apos;utente</h3>
        <ul>
          <li>
            <strong>Identificativo Telegram</strong> (user_id, username): necessario per operare
            il bot e associare i dati all&apos;account.
            Base giuridica: esecuzione del contratto (Art. 6(1)(b)).
          </li>
          <li>
            <strong>Messaggi testuali e foto scontrino</strong> inviati al bot: elaborati per
            estrarre e categorizzare le spese. Il testo grezzo non è archiviato in modo permanente
            dopo l&apos;elaborazione; vengono conservati solo i dati strutturati (importo,
            categoria, data). Base giuridica: esecuzione del contratto (Art. 6(1)(b)).
          </li>
          <li>
            <strong>Messaggi vocali</strong> (solo piano Pro): trasmessi a Google Vertex AI
            (Gemini 2.0) per la sola trascrizione testuale. <strong>Nessuna caratteristica
            biometrica vocale viene estratta o conservata</strong>; l&apos;audio non è
            archiviato dopo la trascrizione. Base giuridica: esecuzione del contratto (Art. 6(1)(b)).
          </li>
          <li>
            <strong>Email e password</strong> (solo utenti web app): per autenticazione.
            La password è conservata in forma di hash irreversibile (bcrypt).
            Base giuridica: esecuzione del contratto (Art. 6(1)(b)).
          </li>
          <li>
            <strong>Dati finanziari</strong> (importi, categorie, conti, abbonamenti, obiettivi
            di risparmio dichiarati con relativo avanzamento, solo piano Pro): inseriti
            volontariamente per la gestione delle spese personali. Base giuridica: esecuzione
            del contratto (Art. 6(1)(b)). La fornitura è facoltativa nel merito (nessun obbligo
            di inserire ogni spesa), ma necessaria per usufruire delle funzionalità del servizio.
          </li>
        </ul>

        <h3>2.2 Dati raccolti automaticamente</h3>
        <ul>
          <li>
            <strong>Log tecnici</strong> (timestamp, tipo operazione, indirizzo IP, user agent):
            per diagnostica, sicurezza e prevenzione di abusi del servizio.
            Base giuridica: <em>interesse legittimo</em> (Art. 6(1)(f)); interesse specifico:
            garantire l&apos;integrità e la sicurezza del sistema e prevenire accessi non
            autorizzati. Il trattamento è necessario e proporzionato; i log non contengono
            dati finanziari e vengono eliminati entro 90 giorni.
            Conservazione: 90 giorni dall&apos;evento.
          </li>
          <li>
            <strong>Dati di utilizzo aggregati</strong> (numero di messaggi per tipo di input,
            funzionalità usate): per migliorare il prodotto e rilevare malfunzionamenti.
            Base giuridica: <em>interesse legittimo</em> (Art. 6(1)(f)); interesse specifico:
            miglioramento continuo del servizio. I dati sono aggregati e non consentono
            l&apos;identificazione del singolo utente.
          </li>
          <li>
            <strong>Controllo qualità interno delle funzionalità automatiche</strong>: per
            garantire il corretto funzionamento di funzionalità che analizzano le spese in modo
            automatico (es. raggruppamento delle voci di spesa simili nei grafici), un numero
            limitato di persone del nostro team può consultare, in forma aggregata, le
            descrizioni delle spese scritte dagli utenti. Base giuridica: <em>interesse
            legittimo</em> (Art. 6(1)(f)); interesse specifico: verificare la qualità di
            funzionalità che operano senza supervisione umana in tempo reale.
          </li>
          <li>
            <strong>Cookie e identificatori analitici</strong>: solo previo consenso esplicito
            dell&apos;utente (vedi <Link href="/cookies">Cookie Policy</Link>).
            Base giuridica: consenso (Art. 6(1)(a)).
          </li>
          <li>
            <strong>Email lista d&apos;attesa beta</strong> (tramite form Tally.so): raccolta
            su base consenso dell&apos;utente che compila il form, ai fini di informarlo del
            lancio del servizio. <strong>Durante la fase beta</strong>, se i posti disponibili
            lo consentono, la compilazione del form può comportare la creazione immediata di
            un account Expensum attivo (email, password generata, accesso alla web app) e
            l&apos;invio delle relative credenziali via email; in tal caso il trattamento dei
            dati dell&apos;account segue le regole della Sezione 2.1 (base giuridica: esecuzione
            del contratto, Art. 6(1)(b)) anziché quelle della lista d&apos;attesa.
            Base giuridica per l&apos;iscrizione alla lista d&apos;attesa in sé: consenso
            (Art. 6(1)(a)), revocabile in qualsiasi momento scrivendo a
            <a href="mailto:expensum.finance@gmail.com"> expensum.finance@gmail.com</a>.
          </li>
        </ul>
      </section>

      <section>
        <h2>3. Destinatari e responsabili del trattamento</h2>
        <p>
          I dati sono condivisi esclusivamente con i seguenti soggetti, nella misura strettamente
          necessaria alla fornitura del servizio, in qualità di Responsabili del trattamento
          (Art. 28 GDPR) o Titolari autonomi, come indicato:
        </p>

        <table className={styles.vendorTable}>
          <thead>
            <tr>
              <th>Fornitore</th>
              <th>Finalità</th>
              <th>Paese</th>
              <th>Base giuridica</th>
              <th>Garanzie trasferimento</th>
            </tr>
          </thead>
          <tbody>
            <tr>
              <td><strong>Telegram Messenger Inc.</strong></td>
              <td>Canale di comunicazione principale, titolare autonomo per i dati sulla piattaforma Telegram</td>
              <td>UAE / Dubai</td>
              <td>Contratto (Art. 6(1)(b))</td>
              <td>SCC (Art. 46(2)(c) GDPR)</td>
            </tr>
            <tr>
              <td><strong>Mistral AI</strong></td>
              <td>Analisi NLP</td>
              <td>Francia (UE)</td>
              <td>Contratto (Art. 6(1)(b))</td>
              <td>Nessun trasferimento extra-UE</td>
            </tr>
            <tr>
              <td><strong>Mistral AI</strong></td>
              <td>Agente conversazionale AI</td>
              <td>Francia (UE)</td>
              <td>Contratto (Art. 6(1)(b))</td>
              <td>Nessun trasferimento extra-UE</td>
            </tr>
            <tr>
              <td><strong>Google Vertex AI</strong> (Gemini 2.0)</td>
              <td>Analisi NLP (solo piano Pro), elaborazione vincolata alla region UE tramite parametro <code>location</code> impostato nel nostro codice</td>
              <td>Francoforte (UE)</td>
              <td>Contratto (Art. 6(1)(b))</td>
              <td>Nessun trasferimento extra-UE</td>
            </tr>
            <tr>
              <td><strong>Tesseract OCR</strong></td>
              <td>Riconoscimento testo da foto scontrino, elaborazione locale sul server Netcup, nessun dato trasmesso a terzi</td>
              <td>Italia (server Netcup DE)</td>
              <td>Contratto (Art. 6(1)(b))</td>
              <td>Trattamento interno UE</td>
            </tr>
            <tr>
              <td><strong>Notion Labs Inc.</strong></td>
              <td>Archiviazione dati finanziari nel workspace Notion dell&apos;utente, il collegamento è facoltativo e a scelta dell&apos;utente (alternativa disponibile: DBMS su server UE)</td>
              <td>USA</td>
              <td>Contratto (Art. 6(1)(b))</td>
              <td>SCC (Art. 46(2)(c))</td>
            </tr>
            <tr>
              <td><strong>Netcup GmbH</strong></td>
              <td>Hosting VPS, database PostgreSQL, archiviazione dati applicazione</td>
              <td>Germania (UE)</td>
              <td>Interesse legittimo (Art. 6(1)(f)); fornitura infrastruttura necessaria al servizio</td>
              <td>Trattamento interno UE</td>
            </tr>
            <tr>
              <td><strong>Google Analytics 4</strong></td>
              <td>Statistiche aggregate di utilizzo del sito web (solo con consenso)</td>
              <td>USA</td>
              <td>Consenso (Art. 6(1)(a))</td>
              <td>SCC (Art. 46(2)(c))</td>
            </tr>
            <tr>
              <td><strong>Meta Platforms Inc.</strong> (Meta Pixel)</td>
              <td>Misurazione conversioni e ottimizzazione campagne (solo con consenso)</td>
              <td>USA</td>
              <td>Consenso (Art. 6(1)(a))</td>
              <td>SCC (Art. 46(2)(c))</td>
            </tr>
            <tr>
              <td><strong>PostHog Inc.</strong></td>
              <td>Analytics prodotto pseudonimizzata, funnel, eventi UX (solo con consenso)</td>
              <td>UE (server EU region)</td>
              <td>Consenso (Art. 6(1)(a))</td>
              <td>Trattamento interno UE</td>
            </tr>
            <tr>
              <td><strong>Tally.so</strong></td>
              <td>Per sviluppo form</td>
              <td>Belgio (UE)</td>
              <td>Consenso (Art. 6(1)(a))</td>
              <td>Trattamento interno UE</td>
            </tr>
            <tr>
              <td><strong>Brevo (Sendinblue SA)</strong></td>
              <td>Invio email agli iscritti alla lista d&apos;attesa beta e, se viene creato un
              account beta, email transazionale con le credenziali di accesso</td>
              <td>Francia (UE)</td>
              <td>Consenso (Art. 6(1)(a)) per l&apos;email di lista d&apos;attesa; Contratto
              (Art. 6(1)(b)) per l&apos;email transazionale con le credenziali di accesso</td>
              <td>Trattamento interno UE</td>
            </tr>
            <tr>
              <td><strong>Stripe Inc.</strong> (futuro)</td>
              <td>Gestione pagamenti piani disponibili sulla piattaforma, <em>non ancora attivo</em></td>
              <td>USA/IE</td>
              <td>Contratto (Art. 6(1)(b))</td>
              <td>SCC (Art. 46(2)(c))</td>
            </tr>
          </tbody>
        </table>

        <p className={styles.legalNote}>
          I fornitori basati fuori UE operano sulla base di Clausole Contrattuali Standard (SCC)
          approvate dalla Commissione Europea ai sensi dell&apos;Art. 46(2)(c) GDPR.
          L&apos;utente può richiedere copia delle garanzie in vigore scrivendo a
          <a href="mailto:expensum.finance@gmail.com"> expensum.finance@gmail.com</a>.
        </p>
      </section>

      <section>
        <h2>4. Trasferimento dei dati fuori dall&apos;UE</h2>
        <p>
          Alcuni fornitori (Meta, Telegram, Notion, Stripe) sono stabiliti negli USA o
          in paesi extra-UE. Il trasferimento avviene esclusivamente sulla base di Clausole
          Contrattuali Standard (SCC) ai sensi dell&apos;Art. 46(2)(c) GDPR, che garantiscono
          un livello di protezione equivalente a quello europeo.
        </p>
        <p>
          <strong>Mistral AI</strong>, fornitore principale per l&apos;analisi delle spese, è
          un&apos;azienda europea (Francia) e il trattamento avviene interamente in territorio
          UE, senza trasferimenti extra-UE. Questo è un fattore deliberato nella scelta
          dello stack AI di Expensum.
        </p>
        <p>
          <strong>Google Vertex AI</strong> (usato solo per la trascrizione vocale, piano Pro)
          è configurato per elaborare i dati esclusivamente nella region europea di Francoforte
          (<code>europe-west3</code>), impostata esplicitamente nel nostro codice tramite il
          parametro <code>location</code> passato ad ogni chiamata API. Non essendoci alcun
          trasferimento extra-UE per questo trattamento, non si applicano le SCC.
        </p>
        <p>
          <strong>Netcup GmbH</strong> (hosting e database) è tedesca e opera esclusivamente
          in Germania.
        </p>
        <p>
          <strong>Backend Notion e residenza dei dati finanziari.</strong> Se scegli di
          collegare il tuo workspace Notion come backend per i dati finanziari, tali dati
          (spese, entrate, categorie, conti, ecc.) vengono scritti e letti direttamente nel
          tuo workspace tramite l&apos;API ufficiale Notion, previa tua autorizzazione OAuth.
          Notion Labs, Inc. ha sede negli Stati Uniti e, salvo che tu abbia attivato opzioni
          di data residency UE sul tuo account Notion (disponibili solo su piani Enterprise
          Notion), i tuoi dati finanziari potrebbero essere conservati ed elaborati al di
          fuori dello Spazio Economico Europeo, sulla base delle SCC stipulate da Notion.
          Expensum non ha controllo sulle garanzie di trasferimento applicate da Notion e
          agisce come intermediario tecnico che trasmette i dati per tuo conto, su tua
          istruzione esplicita. <strong>Se preferisci mantenere i tuoi dati esclusivamente
          su infrastruttura europea, puoi scegliere il backend PostgreSQL</strong>, ospitato
          sui nostri server in UE (Germania, Netcup GmbH), senza alcun trasferimento verso
          paesi terzi.
        </p>
      </section>

      <section>
        <h2>5. Conservazione dei dati</h2>
        <ul>
          <li><strong>Dati account e finanziari</strong>: conservati fino alla cancellazione volontaria dell&apos;account da parte dell&apos;utente.</li>
          <li><strong>Log tecnici</strong> (inclusi IP): 90 giorni dall&apos;evento, poi eliminazione automatica.</li>
          <li><strong>Messaggi vocali originali</strong>: non conservati, eliminati immediatamente dopo la trascrizione.</li>
          <li><strong>Dati di consenso cookie</strong>: 6 mesi (durata del cookie di consenso).</li>
          <li><strong>Email lista d&apos;attesa</strong> (Tally): fino al lancio del servizio o alla revoca del consenso, se precedente, salvo che il form abbia generato la creazione di un account beta, nel qual caso si applica la regola &quot;Dati account e finanziari&quot; sopra.</li>
          <li><strong>Backup</strong>: i backup del database vengono eliminati entro 30 giorni dalla cancellazione dell&apos;account.</li>
        </ul>
        <p>
          Alla scadenza di ciascun periodo i dati sono eliminati o resi definitivamente anonimi,
          nel rispetto del principio di limitazione della conservazione (Art. 5(1)(e) GDPR).
        </p>
      </section>

      <section>
        <h2>6. Trattamenti automatizzati e intelligenza artificiale</h2>
        <p>
          Expensum utilizza modelli di linguaggio (LLM) per analizzare automaticamente le spese
          inserite dall&apos;utente. Questo costituisce un <strong>trattamento automatizzato</strong>
          ai sensi dell&apos;Art. 22 GDPR.
        </p>
        <p>
          <strong>Tale trattamento non produce decisioni con effetti giuridici o significativi
          per l&apos;utente</strong>: l&apos;AI categorizza e struttura i dati finanziari forniti
          dall&apos;utente a soli fini organizzativi personali. Non vengono adottate decisioni
          automatiche su credito, assicurazioni, occupazione o altri ambiti con effetti giuridici
          (Art. 22(1) GDPR non si applica).
        </p>
        <p>
          L&apos;utente può sempre correggere qualsiasi risultato prodotto dall&apos;AI
          (importo errato, categoria sbagliata, ecc.) e può rinunciare all&apos;uso del bot AI
          in qualsiasi momento.
        </p>
        <p>
          Ai sensi dell&apos;Art. 50 del Regolamento UE sull&apos;Intelligenza Artificiale
          (AI Act, Reg. UE 2024/1689), l&apos;utente è informato che le risposte generate da
          Moneo sono prodotte automaticamente da un sistema AI. Dettagli sui modelli utilizzati:
          <Link href="/come-funziona-moneo"> Come funziona l&apos;AI</Link>.
        </p>
      </section>

      <section>
        <h2>7. Diritti dell&apos;interessato</h2>
        <p>Ai sensi degli Artt. 15–22 GDPR, l&apos;utente ha diritto di:</p>
        <ul>
          <li><strong>Accesso</strong> (Art. 15): ottenere copia dei propri dati personali trattati da Expensum.</li>
          <li><strong>Rettifica</strong> (Art. 16): correggere dati inesatti o incompleti.</li>
          <li><strong>Cancellazione (&ldquo;diritto all&apos;oblio&rdquo;)</strong> (Art. 17): richiedere la cancellazione dell&apos;account e di tutti i dati associati.</li>
          <li><strong>Limitazione del trattamento</strong> (Art. 18): limitare il trattamento in determinati casi (es. contestazione dell&apos;esattezza dei dati).</li>
          <li><strong>Portabilità</strong> (Art. 20): ricevere i propri dati finanziari in formato strutturato e leggibile da macchina (JSON o CSV).</li>
          <li><strong>Opposizione</strong> (Art. 21): opporsi in qualsiasi momento al trattamento basato su interesse legittimo o a finalità di marketing diretto.</li>
          <li><strong>Revoca del consenso</strong> (Art. 7(3)): revocare in qualsiasi momento il consenso prestato (per cookie analitici/marketing, email lista d&apos;attesa), senza pregiudizio per la liceità del trattamento effettuato prima della revoca.</li>
        </ul>
        <p>
          I diritti possono essere esercitati direttamente dalla sezione
          <strong> Impostazioni → Privacy e dati</strong> della web app (accesso, portabilità,
          cancellazione account), oppure scrivendo a
          <a href="mailto:expensum.finance@gmail.com"> expensum.finance@gmail.com</a>.
          Tempo di risposta: 30 giorni (Art. 12(3) GDPR). Target operativo: 24 ore.
        </p>
        <p>
          L&apos;utente ha inoltre il diritto di proporre reclamo al
          <strong> Garante per la Protezione dei Dati Personali</strong> (
          <a href="https://www.garanteprivacy.it" target="_blank" rel="noopener noreferrer">
            garanteprivacy.it
          </a>), ai sensi dell&apos;Art. 77 GDPR.
        </p>
      </section>

      <section>
        <h2>8. Sicurezza e violazioni dei dati</h2>
        <p>
          Expensum adotta misure tecniche e organizzative adeguate ai sensi dell&apos;Art. 32
          GDPR, tra cui: comunicazioni cifrate (HTTPS/TLS), hashing irreversibile delle password
          (bcrypt), accesso al database ristretto via socket Unix (nessuna porta esposta su rete
          pubblica), rate limiting per prevenire abusi, separazione dei dati finanziari dai log
          tecnici.
        </p>
        <p>
          In caso di violazione dei dati personali (data breach) che comporti un rischio elevato
          per i diritti e le libertà degli utenti, il Titolare notificherà gli interessati senza
          ingiustificato ritardo, ai sensi dell&apos;Art. 34 GDPR, e provvederà alla notifica
          al Garante entro 72 ore dalla scoperta (Art. 33 GDPR).
        </p>
      </section>

      <section>
        <h2>9. Cookie</h2>
        <p>
          Expensum utilizza cookie tecnici (necessari, sempre attivi) e, previo consenso
          dell&apos;utente, cookie analitici e di marketing. Per l&apos;elenco completo dei
          cookie, i relativi fornitori, le finalità e le modalità di gestione delle preferenze,
          consulta la <Link href="/cookies">Cookie Policy</Link>.
        </p>
      </section>

      <section>
        <h2>10. Modifiche alla presente informativa</h2>
        <p>
          Il Titolare si riserva il diritto di modificare la presente informativa per riflettere
          variazioni normative, tecnologiche o del servizio. Le modifiche saranno comunicate
          tramite notifica Telegram o email almeno <strong>15 giorni prima </strong>
          dell&apos;entrata in vigore.
        </p>
        <p>
          Per i trattamenti basati su consenso, eventuali modifiche sostanziali che amplino le
          finalità di trattamento richiederanno il <strong>rinnovo esplicito del consenso</strong>
          da parte dell&apos;utente (Art. 7 GDPR). Il semplice utilizzo continuato del servizio
          non costituisce accettazione di modifiche che richiedano nuovo consenso.
        </p>
      </section>
    </>
  );
}
