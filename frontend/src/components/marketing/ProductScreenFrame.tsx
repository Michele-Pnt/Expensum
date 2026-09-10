import {
  BarChart3,
  CalendarDays,
  Check,
  ChevronRight,
  CircleDollarSign,
  Home,
  MessageCircle,
  Mic,
  Plus,
  Target,
  TrendingDown,
  WalletCards,
} from "lucide-react";
import { PRODUCT_SCREEN_CONTENT } from "./productScreenContent";
import styles from "./ProductScreenFrame.module.css";

export type ProductScreenKind = "capture" | "overview" | "goals" | "report";

type ProductScreenFrameProps = { kind: ProductScreenKind; label?: string; compact?: boolean };

const titles: Record<ProductScreenKind, string> = {
  capture: "Registra una spesa in chat",
  overview: "Controlla disponibilità e movimenti",
  goals: "Segui i tuoi obiettivi di risparmio",
  report: "Consulta i report automatici",
};

export default function ProductScreenFrame({ kind, label = "Expensum", compact = false }: ProductScreenFrameProps) {
  return (
    <section className={`${styles.preview} ${compact ? styles.compact : ""}`} aria-label={`${label}: ${titles[kind]}`}>
      <header className={styles.appHeader}>
        <span className={styles.wordmark}>{label}</span>
        <span className={styles.liveStatus}><i /> Sincronizzato</span>
      </header>
      <div className={styles.viewport}>
        {kind === "capture" && <CaptureScreen />}
        {kind === "overview" && <OverviewScreen />}
        {kind === "goals" && <GoalsScreen />}
        {kind === "report" && <ReportScreen />}
      </div>
      <PreviewNavigation active={kind} />
    </section>
  );
}

function CaptureScreen() {
  const { transaction } = PRODUCT_SCREEN_CONTENT.capture;
  return (
    <div className={styles.screen}>
      <div className={styles.contextLine}>
        <div><span className={styles.eyebrow}>REGISTRA</span><h3>Ciao, Michele</h3></div>
        <span className={styles.contextBadge}>Settembre</span>
      </div>
      <div className={styles.conversation}>
        <div className={styles.userBubble}>Ieri sushi 24 euro</div>
        <div className={styles.assistantBubble}>
          <span className={styles.confirmIcon}><Check size={15} strokeWidth={2.5} /></span>
          <div><strong>Spesa registrata</strong><span>Ho aggiornato il tuo mese.</span></div>
        </div>
        <article className={styles.transactionCard}>
          <div className={styles.transactionIcon}><CircleDollarSign size={20} /></div>
          <div className={styles.transactionMain}><strong>{transaction.name}</strong><span>{transaction.category}</span></div>
          <strong className={styles.amount}>−{transaction.amount}</strong>
          <div className={styles.transactionMeta}><span>{transaction.account}</span><span>{transaction.date}</span></div>
        </article>
      </div>
      <div className={styles.quickActions}><span>Spesa veloce</span><button>Pranzo</button><button>Spesa</button></div>
      <div className={styles.composer}><Plus size={17} /><span>Scrivi un messaggio</span><Mic size={18} /></div>
    </div>
  );
}

function OverviewScreen() {
  const content = PRODUCT_SCREEN_CONTENT.overview;
  return (
    <div className={styles.screen}>
      <div className={styles.contextLine}>
        <div><span className={styles.eyebrow}>ANALYTICS</span><h3>Oggi</h3></div>
        <span className={styles.contextBadge}>Settembre</span>
      </div>
      <article className={styles.balanceCard}>
        <span>Budget disponibile questo mese</span><strong>{content.available}</strong>
        <div className={styles.balanceMeta}><span>{content.spent} spesi</span><span><TrendingDown size={13} /> {content.delta}</span></div>
        <div className={styles.budgetTrack}><i /></div>
      </article>
      <div className={styles.sectionHeading}><strong>Ultimi movimenti</strong><span>Vedi tutti <ChevronRight size={14} /></span></div>
      <div className={styles.movements}>
        {content.movements.map((movement) => (
          <div className={styles.movement} key={movement.name}>
            <span className={styles.movementIcon}><WalletCards size={17} /></span>
            <div><strong>{movement.name}</strong><span>{movement.category}</span></div>
            <b className={movement.amount.startsWith("+") ? styles.positive : ""}>{movement.amount}</b>
          </div>
        ))}
      </div>
    </div>
  );
}

function GoalsScreen() {
  const goal = PRODUCT_SCREEN_CONTENT.goals.items[0];
  return (
    <div className={styles.screen}>
      <div className={styles.contextLine}>
        <div><span className={styles.eyebrow}>PIANIFICA</span><h3>Obiettivi di risparmio</h3></div>
        <button className={styles.newGoal}><Plus size={15} /> Nuovo</button>
      </div>
      <article className={styles.goalCard}>
        <div className={styles.goalTop}>
          <span className={styles.goalIcon}><Target size={19} /></span>
          <div><strong>{goal.name}</strong><span>{goal.type}</span></div><b>{goal.status}</b>
        </div>
        <div className={styles.goalAmounts}><strong>{goal.current}</strong><span>di {goal.target}</span><b>{goal.progress}%</b></div>
        <div className={styles.goalTrack}><i style={{ width: `${goal.progress}%` }} /></div>
        <p>{goal.detail}</p>
        <footer><CalendarDays size={15} /><span>Data prevista</span><strong>{goal.eta}</strong></footer>
      </article>
      <div className={styles.goalHint}><span>Prossimo passo</span><strong>Metti da parte 80 € questo mese</strong></div>
    </div>
  );
}

function ReportScreen() {
  const { items } = PRODUCT_SCREEN_CONTENT.report;
  return (
    <div className={styles.screen}>
      <div className={styles.contextLine}>
        <div><span className={styles.eyebrow}>ANALIZZA</span><h3>Storico report</h3></div>
        <span className={styles.contextBadge}>Automatici</span>
      </div>
      <p className={styles.screenIntro}>Ritrova analisi, variazioni e indicazioni utili in un unico posto.</p>
      <div className={styles.reportList}>
        {items.map((item, index) => (
          <article className={styles.reportCard} key={`${item.type}-${item.date}`}>
            <span className={styles.reportIcon}>{index ? <BarChart3 size={20} /> : <CalendarDays size={20} />}</span>
            <div><span>REPORT {item.type.toUpperCase()}</span><strong>{item.date}</strong><small>{index ? "Analisi completa del mese" : "Il punto sugli ultimi 7 giorni"}</small></div>
            <b><Check size={13} /> {item.status}</b><ChevronRight className={styles.reportArrow} size={18} />
          </article>
        ))}
      </div>
      <div className={styles.reportNote}><Check size={16} /><span>Il prossimo mini report arriva lunedì.</span></div>
    </div>
  );
}

function PreviewNavigation({ active }: { active: ProductScreenKind }) {
  const entries = [
    { label: "Home", icon: Home, selected: active === "overview" },
    { label: "Analytics", icon: BarChart3, selected: active === "report" },
    { label: "Registra", icon: Plus, selected: active === "capture", primary: true },
    { label: "Obiettivi", icon: Target, selected: active === "goals" },
    { label: "Altro", icon: MessageCircle, selected: false },
  ];
  return (
    <nav className={styles.previewNav} aria-label="Navigazione dell’app in anteprima">
      {entries.map(({ label, icon: Icon, selected, primary }) => (
        <span className={`${styles.navItem} ${selected ? styles.navSelected : ""} ${primary ? styles.navPrimary : ""}`} key={label}>
          <Icon size={primary ? 19 : 17} /><small>{label}</small>
        </span>
      ))}
    </nav>
  );
}
