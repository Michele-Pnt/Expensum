"use client";

import { Check } from "lucide-react";
import styles from "./abbonamenti.module.css";

export default function Abbonamenti() {
  return (
    <div className={styles.container}>
      <header className={styles.header}>
        <h1>Scegli il tuo Piano</h1>
        <p>Sblocca tutto il potenziale di Moneo con il piano Premium.</p>
      </header>

      <div className={styles.grid}>
        {/* FREE PLAN */}
        <div className={styles.card}>
          <h2 className={styles.planName}>Free</h2>
          <div className={styles.price}>€0<span>/mese</span></div>
          <ul className={styles.features}>
            <li className={styles.feature}><Check className={styles.featureIcon} size={18} /> Inserimento spese illimitato via Chat</li>
            <li className={styles.feature}><Check className={styles.featureIcon} size={18} /> Grafici mensili base (Spese per Conto)</li>
            <li className={styles.feature}><Check className={styles.featureIcon} size={18} /> Scelta tra Avatar Base</li>
          </ul>
          <button className={styles.btn}>Piano Attuale</button>
        </div>

        {/* PREMIUM PLAN */}
        <div className={`${styles.card} ${styles.cardPremium}`}>
          <h2 className={styles.planName}>Premium</h2>
          <div className={styles.price}>€4.99<span>/mese</span></div>
          <ul className={styles.features}>
            <li className={styles.feature}><Check className={styles.featureIcon} size={18} /> Tutto il piano Free</li>
            <li className={styles.feature}><Check className={styles.featureIcon} size={18} /> Accesso completo ad Analytics Avanzati</li>
            <li className={styles.feature}><Check className={styles.featureIcon} size={18} /> Statistiche Risparmio & Trend Storici</li>
            <li className={styles.feature}><Check className={styles.featureIcon} size={18} /> Assistente AI Proattivo & Alert</li>
          </ul>
          <button className={`${styles.btn} ${styles.btnPremium}`}>Esegui l'upgrade</button>
        </div>
      </div>
    </div>
  );
}
