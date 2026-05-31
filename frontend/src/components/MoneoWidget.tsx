"use client";

import styles from "./MoneoWidget.module.css";

export type MoneoState = "idle" | "thinking" | "happy" | "error" | "recording";

interface Props {
  state: MoneoState;
}

export default function MoneoWidget({ state }: Props) {
  return (
    <div className={styles.widget}>
      <div className={`${styles.head} ${styles[state]}`}>
        <div className={styles.earLeft} />
        <div className={styles.earRight} />

        <div className={styles.eyes}>
          <div className={styles.eyeWrap}>
            <div className={styles.eye}>
              <div className={styles.pupil} />
            </div>
            <div className={styles.lid} />
          </div>
          <div className={styles.eyeWrap}>
            <div className={styles.eye}>
              <div className={styles.pupil} />
            </div>
            <div className={`${styles.lid} ${styles.lidRight}`} />
          </div>
        </div>

        <div className={styles.nose} />
        <div className={styles.mouth} />

        <div className={`${styles.cheek} ${styles.cheekLeft}`} />
        <div className={`${styles.cheek} ${styles.cheekRight}`} />
      </div>
      <span className={styles.label}>Moneo</span>
    </div>
  );
}
