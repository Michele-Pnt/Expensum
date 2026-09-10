import { Plus } from "lucide-react";
import styles from "./FaqAccordion.module.css";

type FaqAccordionProps = { items: readonly (readonly [string, string])[] };

export default function FaqAccordion({ items }: FaqAccordionProps) {
  return <div className={styles.list}>
    {items.map(([question, answer]) => <details className={styles.item} key={question}>
      <summary><span>{question}</span><Plus aria-hidden="true" size={19} /></summary>
      <div className={styles.answer}>{answer}</div>
    </details>)}
  </div>;
}
