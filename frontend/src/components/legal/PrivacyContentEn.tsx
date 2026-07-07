import { Link } from "@/i18n/navigation";
import styles from "@/app/[locale]/legal.module.css";

export default function PrivacyContentEn() {
  return (
    <>
      <section>
        <h2>1. Data controller</h2>
        <p>
          <strong>Michele Pinotti</strong><br />
          Italy<br />
          Email: <a href="mailto:expensum.finance@gmail.com">expensum.finance@gmail.com</a>
        </p>
        <p>
          The Controller responds to data subject requests within 30 days of receipt
          (operational target: 24 hours), pursuant to Art. 12(3) GDPR.
        </p>
        <p className={styles.legalNote}>
          <strong>Data Protection Officer (DPO):</strong> No DPO has been appointed, as the
          processing carried out by Expensum does not fall within the cases of mandatory
          designation under Art. 37 GDPR (it is not a public authority, nor large-scale
          processing of special categories of data, nor large-scale systematic monitoring).
        </p>
      </section>

      <section>
        <h2>2. Data processed and purposes</h2>
        <p>
          The service is reserved for <strong>adult users (18 or older)</strong>, verified via
          an explicit attestation required at registration. We do not knowingly collect data
          from minors (Art. 8 GDPR; Italian Legislative Decree 101/2018 — contractual capacity).
        </p>

        <h3>2.1 Data provided directly by the user</h3>
        <ul>
          <li>
            <strong>Telegram identifier</strong> (user_id, username): necessary to operate
            the bot and associate data with the account.
            Legal basis: performance of a contract (Art. 6(1)(b)).
          </li>
          <li>
            <strong>Text messages and receipt photos</strong> sent to the bot: processed to
            extract and categorize expenses. Raw text is not permanently stored after
            processing; only structured data (amount, category, date) is retained.
            Legal basis: performance of a contract (Art. 6(1)(b)).
          </li>
          <li>
            <strong>Voice messages</strong> (Pro plan only): transmitted to Google Vertex AI
            (Gemini 2.0) for text transcription only. <strong>No voice biometric feature
            is extracted or stored</strong>; the audio is not stored after transcription.
            Legal basis: performance of a contract (Art. 6(1)(b)).
          </li>
          <li>
            <strong>Email and password</strong> (web app users only): for authentication.
            The password is stored as an irreversible hash (bcrypt).
            Legal basis: performance of a contract (Art. 6(1)(b)).
          </li>
          <li>
            <strong>Financial data</strong> (amounts, categories, accounts, subscriptions):
            entered voluntarily for managing personal expenses. Legal basis: performance
            of a contract (Art. 6(1)(b)). Providing this data is optional in substance (no
            obligation to log every expense), but necessary to use the service&apos;s features.
          </li>
        </ul>

        <h3>2.2 Data collected automatically</h3>
        <ul>
          <li>
            <strong>Technical logs</strong> (timestamp, operation type, IP address, user agent):
            for diagnostics, security and abuse prevention.
            Legal basis: <em>legitimate interest</em> (Art. 6(1)(f)) — specific interest:
            ensuring system integrity and security and preventing unauthorized access.
            Processing is necessary and proportionate; logs contain no financial data and
            are deleted within 90 days.
            Retention: 90 days from the event.
          </li>
          <li>
            <strong>Aggregated usage data</strong> (number of messages by input type,
            features used): to improve the product and detect malfunctions.
            Legal basis: <em>legitimate interest</em> (Art. 6(1)(f)) — specific interest:
            continuous improvement of the service. Data is aggregated and does not allow
            identification of the individual user.
          </li>
          <li>
            <strong>Cookies and analytics identifiers</strong>: only with the user&apos;s
            explicit prior consent (see <Link href="/cookies">Cookie Policy</Link>).
            Legal basis: consent (Art. 6(1)(a)).
          </li>
          <li>
            <strong>Beta waitlist email</strong> (via Tally.so form): collected on the basis of
            the consent of the user who fills in the form, in order to inform them of the
            service launch. <strong>During the beta phase</strong>, if capacity allows, filling
            in the form may result in the immediate creation of an active Expensum account
            (email, generated password, web app access) and the corresponding credentials
            being sent by email — in that case the account data is processed under the rules
            in Section 2.1 (legal basis: contract performance, Art. 6(1)(b)) instead of the
            waitlist rules.
            Legal basis for the waitlist sign-up itself: consent (Art. 6(1)(a)), withdrawable
            at any time by writing to
            <a href="mailto:expensum.finance@gmail.com"> expensum.finance@gmail.com</a>.
          </li>
        </ul>
      </section>

      <section>
        <h2>3. Recipients and data processors</h2>
        <p>
          Data is shared exclusively with the following parties, to the extent strictly
          necessary to provide the service, acting as Data Processors (Art. 28 GDPR) or
          independent Controllers, as indicated:
        </p>

        <table className={styles.vendorTable}>
          <thead>
            <tr>
              <th>Provider</th>
              <th>Purpose</th>
              <th>Country</th>
              <th>Legal basis</th>
              <th>Transfer safeguards</th>
            </tr>
          </thead>
          <tbody>
            <tr>
              <td><strong>Telegram Messenger Inc.</strong></td>
              <td>Main communication channel — independent controller for data on the Telegram platform</td>
              <td>UAE / Dubai</td>
              <td>Contract (Art. 6(1)(b))</td>
              <td>SCC (Art. 46(2)(c) GDPR)</td>
            </tr>
            <tr>
              <td><strong>Mistral AI</strong></td>
              <td>NLP analysis</td>
              <td>France 🇫🇷 (EU)</td>
              <td>Contract (Art. 6(1)(b))</td>
              <td>No extra-EU transfer</td>
            </tr>
            <tr>
              <td><strong>Mistral AI</strong></td>
              <td>AI conversational agent</td>
              <td>France 🇫🇷 (EU)</td>
              <td>Contract (Art. 6(1)(b))</td>
              <td>No extra-EU transfer</td>
            </tr>
            <tr>
              <td><strong>Google Vertex AI</strong> (Gemini 2.0)</td>
              <td>NLP analysis (Pro plan only), processing restricted to the EU region via the <code>location</code> parameter set in our code</td>
              <td>Frankfurt 🇩🇪 (EU)</td>
              <td>Contract (Art. 6(1)(b))</td>
              <td>No extra-EU transfer</td>
            </tr>
            <tr>
              <td><strong>Tesseract OCR</strong></td>
              <td>Text recognition from receipt photos — local processing on the Netcup server, no data transmitted to third parties</td>
              <td>Italy 🇮🇹 (Netcup DE server)</td>
              <td>Contract (Art. 6(1)(b))</td>
              <td>Internal EU processing</td>
            </tr>
            <tr>
              <td><strong>Notion Labs Inc.</strong></td>
              <td>Storage of financial data in the user&apos;s Notion workspace; the connection is optional and chosen by the user (alternative available: DBMS on EU servers)</td>
              <td>USA 🇺🇸</td>
              <td>Contract (Art. 6(1)(b))</td>
              <td>SCC (Art. 46(2)(c))</td>
            </tr>
            <tr>
              <td><strong>Netcup GmbH</strong></td>
              <td>VPS hosting, PostgreSQL database, application data storage</td>
              <td>Germany 🇩🇪 (EU)</td>
              <td>Legitimate interest (Art. 6(1)(f)) — provision of infrastructure necessary for the service</td>
              <td>Internal EU processing</td>
            </tr>
            <tr>
              <td><strong>Google Analytics 4</strong></td>
              <td>Aggregated website usage statistics (with consent only)</td>
              <td>USA 🇺🇸</td>
              <td>Consent (Art. 6(1)(a))</td>
              <td>SCC (Art. 46(2)(c))</td>
            </tr>
            <tr>
              <td><strong>Meta Platforms Inc.</strong> (Meta Pixel)</td>
              <td>Conversion measurement and campaign optimization (with consent only)</td>
              <td>USA 🇺🇸</td>
              <td>Consent (Art. 6(1)(a))</td>
              <td>SCC (Art. 46(2)(c))</td>
            </tr>
            <tr>
              <td><strong>PostHog Inc.</strong></td>
              <td>Pseudonymized product analytics — funnels, UX events (with consent only)</td>
              <td>EU 🇪🇺 (EU server region)</td>
              <td>Consent (Art. 6(1)(a))</td>
              <td>Internal EU processing</td>
            </tr>
            <tr>
              <td><strong>Tally.so</strong></td>
              <td>Form development</td>
              <td>Belgium 🇧🇪 (EU)</td>
              <td>Consent (Art. 6(1)(a))</td>
              <td>Internal EU processing</td>
            </tr>
            <tr>
              <td><strong>Brevo (Sendinblue SA)</strong></td>
              <td>Sends emails to beta waitlist subscribers and, if a beta account is
              created, a transactional email with login credentials</td>
              <td>France 🇫🇷 (EU)</td>
              <td>Consent (Art. 6(1)(a)) for the waitlist email; Contract (Art. 6(1)(b)) for
              the transactional login-credentials email</td>
              <td>Internal EU processing</td>
            </tr>
            <tr>
              <td><strong>Stripe Inc.</strong> (future)</td>
              <td>Payment management for plans available on the platform — <em>not yet active</em></td>
              <td>USA/IE 🇺🇸🇮🇪</td>
              <td>Contract (Art. 6(1)(b))</td>
              <td>SCC (Art. 46(2)(c))</td>
            </tr>
          </tbody>
        </table>

        <p className={styles.legalNote}>
          Providers based outside the EU operate on the basis of Standard Contractual Clauses
          (SCC) approved by the European Commission pursuant to Art. 46(2)(c) GDPR.
          Users may request a copy of the safeguards in place by writing to
          <a href="mailto:expensum.finance@gmail.com"> expensum.finance@gmail.com</a>.
        </p>
      </section>

      <section>
        <h2>4. Transfer of data outside the EU</h2>
        <p>
          Some providers (Meta, Telegram, Notion, Stripe) are established in the USA or in
          non-EU countries. The transfer takes place exclusively on the basis of Standard
          Contractual Clauses (SCC) pursuant to Art. 46(2)(c) GDPR, which guarantee a level
          of protection equivalent to the European one.
        </p>
        <p>
          <strong>Mistral AI</strong>, the main provider for expense analysis, is a European
          company (France) and processing takes place entirely within EU territory, with no
          extra-EU transfers. This is a deliberate factor in the choice of Expensum&apos;s
          AI stack.
        </p>
        <p>
          <strong>Google Vertex AI</strong> (used only for voice transcription, Pro plan)
          is configured to process data exclusively in the European Frankfurt region
          (<code>europe-west3</code>), explicitly set in our code via the <code>location</code>
          parameter passed with every API call. Since there is no extra-EU transfer for this
          processing, SCCs do not apply.
        </p>
        <p>
          <strong>Netcup GmbH</strong> (hosting and database) is German and operates
          exclusively in Germany.
        </p>
        <p>
          <strong>⚠️ Notion backend and residency of financial data.</strong> If you choose to
          connect your Notion workspace as the backend for your financial data, that data
          (expenses, income, categories, accounts, etc.) is written to and read directly from
          your workspace via the official Notion API, subject to your OAuth authorization.
          Notion Labs, Inc. is based in the United States and, unless you have activated EU
          data residency options on your Notion account (available only on Notion Enterprise
          plans), your financial data may be stored and processed outside the European
          Economic Area, on the basis of the SCCs entered into by Notion. Expensum has no
          control over the transfer safeguards applied by Notion and acts as a technical
          intermediary that transmits data on your behalf, on your explicit instruction.
          <strong> If you prefer to keep your data exclusively on European infrastructure,
          you can choose the PostgreSQL backend</strong>, hosted on our servers in the EU
          (Germany, Netcup GmbH), with no transfer to third countries.
        </p>
      </section>

      <section>
        <h2>5. Data retention</h2>
        <ul>
          <li><strong>Account and financial data</strong>: retained until the user voluntarily deletes their account.</li>
          <li><strong>Technical logs</strong> (including IPs): 90 days from the event, then automatically deleted.</li>
          <li><strong>Original voice messages</strong>: not retained — deleted immediately after transcription.</li>
          <li><strong>Cookie consent data</strong>: 6 months (duration of the consent cookie).</li>
          <li><strong>Waitlist email</strong> (Tally): until the service launch or withdrawal of consent, whichever comes first — unless the form resulted in the creation of a beta account, in which case the &quot;Account and financial data&quot; rule above applies.</li>
          <li><strong>Backups</strong>: database backups are deleted within 30 days of account deletion.</li>
        </ul>
        <p>
          At the end of each period, data is deleted or permanently anonymized, in compliance
          with the storage limitation principle (Art. 5(1)(e) GDPR).
        </p>
      </section>

      <section>
        <h2>6. Automated processing and artificial intelligence</h2>
        <p>
          Expensum uses language models (LLMs) to automatically analyze expenses entered by
          the user. This constitutes <strong>automated processing</strong> under Art. 22 GDPR.
        </p>
        <p>
          <strong>This processing does not produce decisions with legal or similarly
          significant effects on the user</strong>: the AI categorizes and structures the
          financial data provided by the user solely for personal organizational purposes.
          No automated decisions are made regarding credit, insurance, employment or other
          areas with legal effects (Art. 22(1) GDPR does not apply).
        </p>
        <p>
          The user can always correct any result produced by the AI (incorrect amount, wrong
          category, etc.) and can opt out of using the AI bot at any time.
        </p>
        <p>
          Pursuant to Art. 50 of the EU Artificial Intelligence Regulation (AI Act, Reg. EU
          2024/1689), the user is informed that responses generated by Moneo are produced
          automatically by an AI system. Details on the models used:
          <Link href="/come-funziona-moneo"> How the AI works</Link>.
        </p>
      </section>

      <section>
        <h2>7. Data subject rights</h2>
        <p>Under Arts. 15–22 GDPR, the user has the right to:</p>
        <ul>
          <li><strong>Access</strong> (Art. 15): obtain a copy of their personal data processed by Expensum.</li>
          <li><strong>Rectification</strong> (Art. 16): correct inaccurate or incomplete data.</li>
          <li><strong>Erasure (&ldquo;right to be forgotten&rdquo;)</strong> (Art. 17): request deletion of the account and all associated data.</li>
          <li><strong>Restriction of processing</strong> (Art. 18): restrict processing in certain cases (e.g. contesting the accuracy of the data).</li>
          <li><strong>Portability</strong> (Art. 20): receive their financial data in a structured, machine-readable format (JSON or CSV).</li>
          <li><strong>Objection</strong> (Art. 21): object at any time to processing based on legitimate interest or for direct marketing purposes.</li>
          <li><strong>Withdrawal of consent</strong> (Art. 7(3)): withdraw consent at any time (for analytics/marketing cookies, waitlist email), without affecting the lawfulness of processing carried out before withdrawal.</li>
        </ul>
        <p>
          Rights can be exercised directly from the
          <strong> Settings → Privacy and data</strong> section of the web app (access,
          portability, account deletion), or by writing to
          <a href="mailto:expensum.finance@gmail.com"> expensum.finance@gmail.com</a>.
          Response time: 30 days (Art. 12(3) GDPR). Operational target: 24 hours.
        </p>
        <p>
          The user also has the right to lodge a complaint with the
          <strong> Italian Data Protection Authority (Garante per la Protezione dei Dati
          Personali)</strong> (
          <a href="https://www.garanteprivacy.it" target="_blank" rel="noopener noreferrer">
            garanteprivacy.it
          </a>), pursuant to Art. 77 GDPR.
        </p>
      </section>

      <section>
        <h2>8. Security and data breaches</h2>
        <p>
          Expensum adopts technical and organizational measures appropriate under Art. 32
          GDPR, including: encrypted communications (HTTPS/TLS), irreversible password hashing
          (bcrypt), database access restricted via Unix socket (no port exposed on the public
          network), rate limiting to prevent abuse, separation of financial data from
          technical logs.
        </p>
        <p>
          In the event of a personal data breach that poses a high risk to the rights and
          freedoms of users, the Controller will notify data subjects without undue delay,
          pursuant to Art. 34 GDPR, and will notify the Data Protection Authority within 72
          hours of discovery (Art. 33 GDPR).
        </p>
      </section>

      <section>
        <h2>9. Cookies</h2>
        <p>
          Expensum uses technical cookies (necessary, always active) and, subject to the
          user&apos;s consent, analytics and marketing cookies. For the full list of cookies,
          their providers, purposes and how to manage preferences, see the
          <Link href="/cookies">Cookie Policy</Link>.
        </p>
      </section>

      <section>
        <h2>10. Changes to this notice</h2>
        <p>
          The Controller reserves the right to amend this notice to reflect regulatory,
          technological or service changes. Changes will be communicated via Telegram
          notification or email at least <strong>15 days before</strong> they take effect.
        </p>
        <p>
          For processing based on consent, any substantial changes that expand the purposes
          of processing will require the <strong>explicit renewal of consent</strong> by the
          user (Art. 7 GDPR). Simply continuing to use the service does not constitute
          acceptance of changes that require new consent.
        </p>
      </section>
    </>
  );
}
