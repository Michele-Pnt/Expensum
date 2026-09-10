"use client";

import { BarChart3, Compass, Target } from "lucide-react";
import type { AnalyticsDestination } from "../types";
import styles from "./analytics.module.css";

type AnalyticsNavigationProps = {
  destination: AnalyticsDestination;
  onDestinationChange: (destination: AnalyticsDestination) => void;
};

const destinations = [
  { id: "today", label: "Oggi", icon: BarChart3 },
  { id: "explore", label: "Esplora", icon: Compass },
  { id: "plan", label: "Pianifica", icon: Target },
] as const;

/** Navigazione locale che mantiene le stesse destinazioni su mobile e desktop. */
export default function AnalyticsNavigation({ destination, onDestinationChange }: AnalyticsNavigationProps) {
  return (
    <nav className={styles.navigation} aria-label="Sezioni analytics" data-tour="analytics-tabs">
      {destinations.map(({ id, label, icon: Icon }) => {
        const selected = destination === id;
        return (
          <button
            key={id}
            type="button"
            className={selected ? `${styles.navigationItem} ${styles.navigationItemActive}` : styles.navigationItem}
            aria-current={selected ? "page" : undefined}
            onClick={() => onDestinationChange(id)}
          >
            <Icon size={18} strokeWidth={1.75} aria-hidden="true" />
            <span>{label}</span>
          </button>
        );
      })}
    </nav>
  );
}
