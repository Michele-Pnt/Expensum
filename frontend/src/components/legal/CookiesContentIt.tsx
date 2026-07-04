import { Link } from "@/i18n/navigation";
import styles from "@/app/[locale]/legal.module.css";

export default function CookiesContentIt() {
  return (
    <>
      <section>
        <h2>1. Cosa sono i cookie</h2>
        <p>
          I cookie sono piccoli file di testo che i siti web salvano nel browser dell&apos;utente. Vengono utilizzati per far funzionare il sito correttamente, ricordare le preferenze e raccogliere statistiche aggregate di utilizzo.
        </p>
        <p>
          Expensum utilizza esclusivamente cookie di prima parte (impostati direttamente da expensum.it) e cookie di terze parti (impostati dai fornitori elencati di seguito), sempre nel rispetto delle preferenze espresse dall&apos;utente tramite il banner cookie.
        </p>
      </section>

      <section>
        <h2>2. Cookie tecnici (sempre attivi)</h2>
        <p>
          I cookie tecnici sono necessari per il funzionamento del sito e non richiedono consenso. Non possono essere disattivati.
        </p>
        <table className={styles.vendorTable}>
          <thead>
            <tr>
              <th>Nome</th>
              <th>Finalità</th>
              <th>Durata</th>
            </tr>
          </thead>
          <tbody>
            <tr>
              <td><code>cc_cookie</code></td>
              <td>Salva le preferenze di consenso cookie dell&apos;utente</td>
              <td>6 mesi</td>
            </tr>
            <tr>
              <td>Cookie di sessione (autenticazione web app)</td>
              <td>Mantiene la sessione autenticata dell&apos;utente nella web app</td>
              <td>Sessione / 30 giorni</td>
            </tr>
            <tr>
              <td><code>csrf_token</code></td>
              <td>Protezione CSRF per le operazioni autenticate</td>
              <td>Sessione</td>
            </tr>
          </tbody>
        </table>
      </section>

      <section>
        <h2>3. Cookie analitici (previo consenso)</h2>
        <p>
          Attivati solo se l&apos;utente accetta la categoria &quot;Analitici&quot; nel banner cookie. Permettono di capire come gli utenti utilizzano il sito, in forma aggregata e anonima.
        </p>
        <table className={styles.vendorTable}>
          <thead>
            <tr>
              <th>Fornitore</th>
              <th>Cookie</th>
              <th>Finalità</th>
              <th>Durata</th>
              <th>Privacy</th>
            </tr>
          </thead>
          <tbody>
            <tr>
              <td><strong>Google Analytics 4</strong></td>
              <td><code>_ga</code>, <code>_gid</code>, <code>_ga_*</code></td>
              <td>Statistiche aggregate: sessioni, pagine visitate, provenienza traffico</td>
              <td>2 anni / 24h</td>
              <td><a href="https://policies.google.com/privacy" target="_blank" rel="noopener noreferrer">Google Privacy Policy</a></td>
            </tr>
            <tr>
              <td><strong>PostHog</strong></td>
              <td><code>ph_*</code>, <code>posthog_*</code></td>
              <td>Analytics prodotto pseudonimizzata: funnel di onboarding, eventi UX, utilizzo funzionalità</td>
              <td>1 anno</td>
              <td><a href="https://posthog.com/privacy" target="_blank" rel="noopener noreferrer">PostHog Privacy Policy</a></td>
            </tr>
          </tbody>
        </table>
      </section>

      <section>
        <h2>4. Cookie di marketing (previo consenso)</h2>
        <p>
          Attivati solo se l&apos;utente accetta la categoria &quot;Marketing&quot; nel banner cookie. Permettono di misurare l&apos;efficacia delle campagne pubblicitarie e di mostrare annunci pertinenti.
        </p>
        <table className={styles.vendorTable}>
          <thead>
            <tr>
              <th>Fornitore</th>
              <th>Cookie</th>
              <th>Finalità</th>
              <th>Durata</th>
              <th>Privacy</th>
            </tr>
          </thead>
          <tbody>
            <tr>
              <td><strong>Meta Pixel</strong> (Facebook/Instagram)</td>
              <td><code>_fbp</code>, <code>_fbc</code></td>
              <td>Tracciamento conversioni, ottimizzazione campagne su Facebook e Instagram</td>
              <td>90 giorni</td>
              <td><a href="https://www.facebook.com/privacy/policy/" target="_blank" rel="noopener noreferrer">Meta Privacy Policy</a></td>
            </tr>
          </tbody>
        </table>
      </section>

      <section>
        <h2>4b. Cookie di domini terzi</h2>
        <p>
          Alcuni cookie analitici e di marketing sono impostati direttamente da domini di terze
          parti (es. <code>*.google-analytics.com</code>, <code>*.facebook.com</code>,
          <code>*.posthog.com</code>). Questi cookie sono soggetti alle rispettive privacy
          policy dei fornitori, linkate nelle tabelle sopra. Expensum non ha accesso ai dati
          raccolti da questi cookie al di fuori di quanto aggregato nelle dashboard dei
          rispettivi fornitori.
        </p>
      </section>

      <section>
        <h2>5. Gestire le preferenze</h2>
        <p>Al primo accesso al sito appare un banner con tre opzioni equiparate:</p>
        <ul>
          <li><strong>Accetta tutto</strong>: attiva cookie analitici e di marketing.</li>
          <li><strong>Rifiuta tutto</strong> (o chiudi il banner con la ×): vengono attivati solo i cookie tecnici necessari.</li>
          <li><strong>Gestisci preferenze</strong>: seleziona singolarmente quali categorie attivare.</li>
        </ul>
        <p>
          Le preferenze vengono ricordate per <strong>6 mesi</strong>. Puoi cambiarle in qualsiasi momento cliccando su &quot;Gestisci preferenze cookie&quot; nel footer oppure cancellando i cookie del browser.
        </p>
        <p>
          Per eliminare i cookie già salvati: apri le impostazioni del tuo browser → Privacy e sicurezza → Cancella dati di navigazione → Spunta &quot;Cookie e altri dati dei siti&quot;.
        </p>
      </section>

      <section>
        <h2>6. Cookie della web app Telegram</h2>
        <p>
          Il bot Telegram di Expensum non utilizza cookie. Il tracciamento avviene tramite l&apos;identificativo Telegram fornito dalla piattaforma, che è soggetto alla <a href="https://telegram.org/privacy" target="_blank" rel="noopener noreferrer">Privacy Policy di Telegram</a>.
        </p>
      </section>

      <section>
        <h2>7. Riferimenti normativi</h2>
        <p>
          Questa Cookie Policy è redatta in conformità al:
        </p>
        <ul>
          <li>Regolamento UE 2016/679 (GDPR)</li>
          <li>D.Lgs. 196/2003 e s.m.i. (Codice Privacy)</li>
          <li>Provvedimento del Garante Privacy del 10 giugno 2021 sui cookie</li>
          <li>Linee guida EDPB n. 5/2019 sul consenso</li>
        </ul>
      </section>

      <section>
        <h2>8. Contatti</h2>
        <p>
          Per qualsiasi domanda sui cookie: <a href="mailto:expensum.finance@gmail.com">expensum.finance@gmail.com</a>
        </p>
        <p>
          Per il trattamento complessivo dei dati personali, consulta la <Link href="/privacy">Privacy Policy</Link>.
        </p>
      </section>
    </>
  );
}
