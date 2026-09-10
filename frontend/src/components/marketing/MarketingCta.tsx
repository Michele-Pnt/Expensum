"use client";

import { useState } from "react";
import { ArrowUpRight } from "lucide-react";
import { openTallyWaitlist } from "@/lib/tallyWaitlist";
import { getReferralCode } from "@/lib/waitlist";
import styles from "./MarketingCta.module.css";

const TALLY_FORM_ID = "44pAAr";

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
  const [referralCode] = useState<string | null>(() => (
    typeof window === "undefined" ? null : getReferralCode(window.location.search)
  ));

  const openWaitlist = () => {
    void openTallyWaitlist(TALLY_FORM_ID, referralCode);
  };

  return (
    <div className={styles.group}>
      {waitlist ? (
        <button className={styles.primary} type="button" onClick={openWaitlist}>
          {label}
          <ArrowUpRight aria-hidden="true" size={18} strokeWidth={1.8} />
        </button>
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
