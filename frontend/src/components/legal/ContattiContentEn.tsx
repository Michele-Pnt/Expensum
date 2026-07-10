import { Link } from "@/i18n/navigation";
import styles from "@/app/[locale]/legal.module.css";

export default function ContattiContentEn() {
  return (
    <>
      <section>
        <h2>1. Write to us</h2>
        <p>
          For support, business inquiries, or any other request you can email us directly.
          We usually reply within 48 business hours.
        </p>
        <div className={styles.contactRow}>
          <span className={styles.contactIcon} aria-hidden="true">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.8} strokeLinecap="round" strokeLinejoin="round">
              <rect x="2" y="4" width="20" height="16" rx="2.5" />
              <path d="m3 6 9 6 9-6" />
            </svg>
          </span>
          <a href="mailto:expensum.finance@gmail.com" className={styles.contactLink}>
            expensum.finance@gmail.com
          </a>
          <a
            href="https://mail.google.com/mail/?view=cm&fs=1&to=expensum.finance@gmail.com"
            target="_blank"
            rel="noopener noreferrer"
            className={styles.contactIcon}
            aria-label="Open in Gmail"
            title="Open in Gmail"
          >
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.8} strokeLinecap="round" strokeLinejoin="round">
              <rect x="2" y="4" width="20" height="16" rx="2.5" />
              <path d="m2 6 10 7 10-7" />
            </svg>
          </a>
        </div>
      </section>

      <section>
        <h2>2. Feedback and bug reports</h2>
        <p>
          Have a suggestion, a feature request, or found a bug? You can send us feedback directly
          from the app: open the <Link href="/feedback">Feedback</Link> section from your
          personal area.
        </p>
        <p>
          Alternatively, you can email us at the address above, describing in as much detail as
          possible the issue you found or the idea you&apos;d like to propose.
        </p>
      </section>

      <section>
        <h2>3. Legal information</h2>
        <div className={styles.legalChipsRow}>
          <Link href="/privacy" className={styles.legalChip}>
            <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.8} strokeLinecap="round" strokeLinejoin="round">
              <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10Z" />
            </svg>
            Privacy Policy
          </Link>
          <Link href="/terms" className={styles.legalChip}>
            <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.8} strokeLinecap="round" strokeLinejoin="round">
              <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8Z" />
              <path d="M14 2v6h6" />
              <path d="M9 13h6M9 17h6" />
            </svg>
            Terms of Service
          </Link>
        </div>
      </section>

      <section>
        <h2>4. Follow us</h2>
        <p>You can also find us on our social channels:</p>
        <div className={styles.socialRow}>
          <a href="https://instagram.com/expensum.finance" target="_blank" rel="noopener noreferrer" className={styles.contactIcon} aria-label="Instagram">
            <svg width="16" height="16" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.8}><rect x="2" y="2" width="20" height="20" rx="5" /><circle cx="12" cy="12" r="5" /><circle cx="17.5" cy="6.5" r="1" fill="currentColor" stroke="none" /></svg>
          </a>
          <a href="https://acesse.one/ite4lxk" target="_blank" rel="noopener noreferrer" className={styles.contactIcon} aria-label="Facebook">
            <svg width="16" height="16" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.8}><path d="M18 2h-3a5 5 0 0 0-5 5v3H7v4h3v8h4v-8h3l1-4h-4V7a1 1 0 0 1 1-1h3z" /></svg>
          </a>
          <a href="https://www.linkedin.com/company/expensum/" target="_blank" rel="noopener noreferrer" className={styles.contactIcon} aria-label="LinkedIn">
            <svg width="16" height="16" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.8} strokeLinecap="round" strokeLinejoin="round">
              <path d="M16 8a6 6 0 0 1 6 6v7h-4v-7a2 2 0 0 0-2-2 2 2 0 0 0-2 2v7h-4v-7a6 6 0 0 1 6-6z" />
              <rect x="2" y="9" width="4" height="12" />
              <circle cx="4" cy="4" r="2" />
            </svg>
          </a>
          <a href="https://www.tiktok.com/@expensum" target="_blank" rel="noopener noreferrer" className={styles.contactIcon} aria-label="TikTok">
            <svg width="16" height="16" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.8} strokeLinecap="round" strokeLinejoin="round">
              <path d="M14 4v10.5a3.5 3.5 0 1 1-3.5-3.5c.35 0 .69.05 1 .14" />
              <path d="M14 4a4.5 4.5 0 0 0 4.5 4.5" />
            </svg>
          </a>
        </div>
      </section>
    </>
  );
}
