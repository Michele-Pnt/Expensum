import { Link } from "@/i18n/navigation";
import styles from "@/app/[locale]/legal.module.css";

export default function CookiesContentEn() {
  return (
    <>
      <section>
        <h2>1. What cookies are</h2>
        <p>
          Cookies are small text files that websites save in the user&apos;s browser. They are used to make the site work properly, remember preferences and collect aggregated usage statistics.
        </p>
        <p>
          Expensum uses exclusively first-party cookies (set directly by expensum.it) and third-party cookies (set by the providers listed below), always in accordance with the preferences expressed by the user via the cookie banner.
        </p>
      </section>

      <section>
        <h2>2. Technical cookies (always active)</h2>
        <p>
          Technical cookies are necessary for the website to function and do not require consent. They cannot be disabled.
        </p>
        <table className={styles.vendorTable}>
          <thead>
            <tr>
              <th>Name</th>
              <th>Purpose</th>
              <th>Duration</th>
            </tr>
          </thead>
          <tbody>
            <tr>
              <td><code>cc_cookie</code></td>
              <td>Stores the user&apos;s cookie consent preferences</td>
              <td>6 months</td>
            </tr>
            <tr>
              <td>Session cookie (web app authentication)</td>
              <td>Keeps the user&apos;s authenticated session in the web app</td>
              <td>Session / 30 days</td>
            </tr>
            <tr>
              <td><code>csrf_token</code></td>
              <td>CSRF protection for authenticated operations</td>
              <td>Session</td>
            </tr>
          </tbody>
        </table>
      </section>

      <section>
        <h2>3. Analytics cookies (with prior consent)</h2>
        <p>
          Activated only if the user accepts the &quot;Analytics&quot; category in the cookie banner. They help us understand how users use the site, in aggregated and anonymous form.
        </p>
        <table className={styles.vendorTable}>
          <thead>
            <tr>
              <th>Provider</th>
              <th>Cookie</th>
              <th>Purpose</th>
              <th>Duration</th>
              <th>Privacy</th>
            </tr>
          </thead>
          <tbody>
            <tr>
              <td><strong>Google Analytics 4</strong></td>
              <td><code>_ga</code>, <code>_gid</code>, <code>_ga_*</code></td>
              <td>Aggregated statistics: sessions, pages visited, traffic source</td>
              <td>2 years / 24h</td>
              <td><a href="https://policies.google.com/privacy" target="_blank" rel="noopener noreferrer">Google Privacy Policy</a></td>
            </tr>
            <tr>
              <td><strong>PostHog</strong></td>
              <td><code>ph_*</code>, <code>posthog_*</code></td>
              <td>Pseudonymized product analytics: onboarding funnel, UX events, feature usage</td>
              <td>1 year</td>
              <td><a href="https://posthog.com/privacy" target="_blank" rel="noopener noreferrer">PostHog Privacy Policy</a></td>
            </tr>
          </tbody>
        </table>
      </section>

      <section>
        <h2>4. Marketing cookies (with prior consent)</h2>
        <p>
          Activated only if the user accepts the &quot;Marketing&quot; category in the cookie banner. They allow us to measure the effectiveness of advertising campaigns and show relevant ads.
        </p>
        <table className={styles.vendorTable}>
          <thead>
            <tr>
              <th>Provider</th>
              <th>Cookie</th>
              <th>Purpose</th>
              <th>Duration</th>
              <th>Privacy</th>
            </tr>
          </thead>
          <tbody>
            <tr>
              <td><strong>Meta Pixel</strong> (Facebook/Instagram)</td>
              <td><code>_fbp</code>, <code>_fbc</code></td>
              <td>Conversion tracking, campaign optimization on Facebook and Instagram</td>
              <td>90 days</td>
              <td><a href="https://www.facebook.com/privacy/policy/" target="_blank" rel="noopener noreferrer">Meta Privacy Policy</a></td>
            </tr>
          </tbody>
        </table>
      </section>

      <section>
        <h2>4b. Third-party domain cookies</h2>
        <p>
          Some analytics and marketing cookies are set directly by third-party domains (e.g.
          <code>*.google-analytics.com</code>, <code>*.facebook.com</code>,
          <code>*.posthog.com</code>). These cookies are subject to the respective privacy
          policies of the providers, linked in the tables above. Expensum has no access to
          the data collected by these cookies beyond what is aggregated in the respective
          providers&apos; dashboards.
        </p>
      </section>

      <section>
        <h2>5. Managing preferences</h2>
        <p>On first visit to the site, a banner appears with three equally weighted options:</p>
        <ul>
          <li><strong>Accept all</strong>: activates analytics and marketing cookies.</li>
          <li><strong>Reject all</strong> (or close the banner with the ×): only necessary technical cookies are activated.</li>
          <li><strong>Manage preferences</strong>: individually select which categories to activate.</li>
        </ul>
        <p>
          Preferences are remembered for <strong>6 months</strong>. You can change them at any time by clicking &quot;Manage cookie preferences&quot; in the footer or by clearing your browser&apos;s cookies.
        </p>
        <p>
          To delete cookies already saved: open your browser settings → Privacy and security → Clear browsing data → Check &quot;Cookies and other site data&quot;.
        </p>
      </section>

      <section>
        <h2>6. Telegram web app cookies</h2>
        <p>
          Expensum&apos;s Telegram bot does not use cookies. Tracking takes place via the Telegram identifier provided by the platform, which is subject to <a href="https://telegram.org/privacy" target="_blank" rel="noopener noreferrer">Telegram&apos;s Privacy Policy</a>.
        </p>
      </section>

      <section>
        <h2>7. Regulatory references</h2>
        <p>
          This Cookie Policy is drafted in compliance with:
        </p>
        <ul>
          <li>EU Regulation 2016/679 (GDPR)</li>
          <li>Italian Legislative Decree 196/2003 as amended (Privacy Code)</li>
          <li>Italian Data Protection Authority measure of 10 June 2021 on cookies</li>
          <li>EDPB Guidelines No. 5/2019 on consent</li>
        </ul>
      </section>

      <section>
        <h2>8. Contact</h2>
        <p>
          For any questions about cookies: <a href="mailto:expensum.finance@gmail.com">expensum.finance@gmail.com</a>
        </p>
        <p>
          For the overall processing of personal data, see the <Link href="/privacy">Privacy Policy</Link>.
        </p>
      </section>
    </>
  );
}
