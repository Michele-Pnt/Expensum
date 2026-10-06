/* eslint-disable @next/next/no-html-link-for-pages -- Registration is a Flask rewrite. */
"use client";

import { ArrowUpRight } from "lucide-react";
import styles from "./MarketingCta.module.css";

type MarketingCtaProps = {
  label: string;
  secondaryLabel?: string;
  href?: string;
  waitlist?: boolean;
};

export default function MarketingCta({
  label,
  secondaryLabel,
  href = "#inizia",
  waitlist = false,
}: MarketingCtaProps) {
  return (
    <div className={styles.group}>
      {waitlist ? (
        <a className={styles.primary} href="/register">
          {label}
          <ArrowUpRight aria-hidden="true" size={18} strokeWidth={1.8} />
        </a>
      ) : (
        <a className={styles.primary} href={href}>
          {label}
          <ArrowUpRight aria-hidden="true" size={18} strokeWidth={1.8} />
        </a>
      )}
      {secondaryLabel && <span className={styles.secondary}>{secondaryLabel}</span>}
    </div>
  );
}
