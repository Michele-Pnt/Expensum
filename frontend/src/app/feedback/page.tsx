"use client";

import { Send } from "lucide-react";
import styles from "./feedback.module.css";

export default function Feedback() {
  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    alert("Feedback inviato a Moneo! Grazie.");
  };

  return (
    <div className={styles.container}>
      <header className={styles.header}>
        <h1>Feedback & Supporto</h1>
        <p>Aiutaci a migliorare Moneo. Inviaci suggerimenti o segnalazioni di bug.</p>
      </header>

      <form className={styles.form} onClick={(e) => handleSubmit(e)}>
        <div className={styles.formGroup}>
          <label className={styles.label}>Il tuo messaggio</label>
          <textarea 
            className={styles.textarea} 
            placeholder="Scrivi qui il tuo feedback..."
            required
          ></textarea>
        </div>
        
        <button type="submit" className={styles.submitBtn}>
          <Send size={18} /> Invia Feedback
        </button>
      </form>
    </div>
  );
}
