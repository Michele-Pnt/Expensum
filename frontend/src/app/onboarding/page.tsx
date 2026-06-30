"use client";

import { useState, useEffect, useCallback } from "react";
import { useRouter } from "next/navigation";
import { getCsrfToken } from "@/lib/csrf";
import {
  Box,
  Typography,
  Button,
  Chip,
  CircularProgress,
  LinearProgress,
  TextField,
  ToggleButton,
  ToggleButtonGroup,
  Switch,
  FormControlLabel,
  Skeleton,
} from "@mui/material";

// ─── Types ────────────────────────────────────────────────────────────────────

interface Lifestyle {
  transport?: string;
  dining?: string;
  hobbies?: string[];
}

interface WizardState {
  language: string;
  currency: string;
  timezone: string;
  lifestyle: Lifestyle;
  budget: string;
  notificationsEnabled: boolean;
  notificationTime: string;
  categories: string[];
  selectedCategories: Set<string>;
}

function getTelegramInitData(): string {
  if (typeof window === "undefined") return "";
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  return (window as any).Telegram?.WebApp?.initData ?? "";
}

async function buildHeaders(): Promise<HeadersInit> {
  const init = getTelegramInitData();
  const csrfToken = await getCsrfToken();
  const headers: Record<string, string> = { "X-CSRFToken": csrfToken };
  if (init) headers["X-Telegram-Init-Data"] = init;
  return headers;
}

// ─── Step components ──────────────────────────────────────────────────────────

function WelcomeStep({ onNext }: { onNext: () => void }) {
  return (
    <Box sx={{ textAlign: "center", py: 4 }}>
      <Typography variant="h4" fontWeight={700} sx={{ mb: 2, color: "var(--color-primary)" }}>
        👋 Benvenuto su Moneo!
      </Typography>
      <Typography variant="body1" sx={{ mb: 4, color: "var(--color-text-2)", maxWidth: 340, mx: "auto" }}>
        In pochi minuti personalizzeremo il tuo spazio in base al tuo stile di vita.
        Ci vorranno meno di 2 minuti.
      </Typography>
      <Button variant="contained" size="large" onClick={onNext} sx={primaryBtnSx}>
        Iniziamo 🚀
      </Button>
    </Box>
  );
}

function LanguageStep({
  value,
  onChange,
  onNext,
  onBack,
}: {
  value: string;
  onChange: (v: string) => void;
  onNext: () => void;
  onBack: () => void;
}) {
  const options = [
    { value: "it", label: "🇮🇹 Italiano" },
    { value: "en", label: "🇬🇧 English" },
  ];
  return (
    <StepWrapper title="Lingua" required onNext={onNext} onBack={onBack} canNext={!!value}>
      <ToggleButtonGroup
        value={value}
        exclusive
        onChange={(_, v) => v && onChange(v)}
        sx={{ display: "flex", gap: 1, flexWrap: "wrap" }}
      >
        {options.map((o) => (
          <ToggleButton key={o.value} value={o.value} sx={toggleBtnSx}>
            {o.label}
          </ToggleButton>
        ))}
      </ToggleButtonGroup>
    </StepWrapper>
  );
}

function CurrencyStep({
  value,
  onChange,
  onNext,
  onBack,
}: {
  value: string;
  onChange: (v: string) => void;
  onNext: () => void;
  onBack: () => void;
}) {
  const options = ["EUR", "USD", "GBP", "CHF"];
  return (
    <StepWrapper title="Valuta principale" required onNext={onNext} onBack={onBack} canNext={!!value}>
      <ToggleButtonGroup
        value={value}
        exclusive
        onChange={(_, v) => v && onChange(v)}
        sx={{ display: "flex", gap: 1, flexWrap: "wrap" }}
      >
        {options.map((o) => (
          <ToggleButton key={o} value={o} sx={toggleBtnSx}>
            {o}
          </ToggleButton>
        ))}
      </ToggleButtonGroup>
    </StepWrapper>
  );
}

function TimezoneStep({
  value,
  onChange,
  onNext,
  onBack,
}: {
  value: string;
  onChange: (v: string) => void;
  onNext: () => void;
  onBack: () => void;
}) {
  const presets = [
    { value: "Europe/Rome", label: "🇮🇹 Roma (CET)" },
    { value: "Europe/London", label: "🇬🇧 Londra (GMT)" },
    { value: "America/New_York", label: "🇺🇸 New York (EST)" },
    { value: "America/Los_Angeles", label: "🇺🇸 Los Angeles (PST)" },
  ];
  return (
    <StepWrapper title="Fuso orario" required onNext={onNext} onBack={onBack} canNext={!!value}>
      <ToggleButtonGroup
        value={value}
        exclusive
        onChange={(_, v) => v && onChange(v)}
        sx={{ display: "flex", flexDirection: "column", gap: 1 }}
      >
        {presets.map((p) => (
          <ToggleButton key={p.value} value={p.value} sx={{ ...toggleBtnSx, justifyContent: "flex-start" }}>
            {p.label}
          </ToggleButton>
        ))}
      </ToggleButtonGroup>
    </StepWrapper>
  );
}

function TransportStep({
  value,
  onChange,
  onNext,
  onBack,
  onSkip,
}: {
  value: string;
  onChange: (v: string) => void;
  onNext: () => void;
  onBack: () => void;
  onSkip: () => void;
}) {
  const options = [
    { value: "auto", label: "🚗 Auto / Moto" },
    { value: "mezzi", label: "🚌 Mezzi pubblici" },
    { value: "piedi", label: "🚶 A piedi / Bici" },
  ];
  return (
    <StepWrapper title="Come ti sposti di solito?" onNext={onNext} onBack={onBack} onSkip={onSkip} canNext={!!value}>
      <ToggleButtonGroup
        value={value}
        exclusive
        onChange={(_, v) => v && onChange(v)}
        sx={{ display: "flex", flexDirection: "column", gap: 1 }}
      >
        {options.map((o) => (
          <ToggleButton key={o.value} value={o.value} sx={{ ...toggleBtnSx, justifyContent: "flex-start" }}>
            {o.label}
          </ToggleButton>
        ))}
      </ToggleButtonGroup>
    </StepWrapper>
  );
}

function DiningStep({
  value,
  onChange,
  onNext,
  onBack,
  onSkip,
}: {
  value: string;
  onChange: (v: string) => void;
  onNext: () => void;
  onBack: () => void;
  onSkip: () => void;
}) {
  const options = [
    { value: "spesso", label: "🍕 Spesso (3+ volte/settimana)" },
    { value: "a_volte", label: "🍽️ A volte (1-2 volte/settimana)" },
    { value: "raramente", label: "🏠 Raramente (cucino quasi sempre)" },
  ];
  return (
    <StepWrapper title="Mangi spesso fuori casa?" onNext={onNext} onBack={onBack} onSkip={onSkip} canNext={!!value}>
      <ToggleButtonGroup
        value={value}
        exclusive
        onChange={(_, v) => v && onChange(v)}
        sx={{ display: "flex", flexDirection: "column", gap: 1 }}
      >
        {options.map((o) => (
          <ToggleButton key={o.value} value={o.value} sx={{ ...toggleBtnSx, justifyContent: "flex-start" }}>
            {o.label}
          </ToggleButton>
        ))}
      </ToggleButtonGroup>
    </StepWrapper>
  );
}

function HobbiesStep({
  value,
  onChange,
  onNext,
  onBack,
  onSkip,
}: {
  value: string[];
  onChange: (v: string[]) => void;
  onNext: () => void;
  onBack: () => void;
  onSkip: () => void;
}) {
  const options = [
    { value: "palestra", label: "💪 Sport / Palestra" },
    { value: "streaming", label: "📺 Streaming / Gaming" },
    { value: "viaggi", label: "✈️ Viaggi" },
    { value: "cultura", label: "🎭 Cinema / Cultura" },
  ];
  const toggle = (v: string) => {
    onChange(value.includes(v) ? value.filter((x) => x !== v) : [...value, v]);
  };
  return (
    <StepWrapper title="Quali sono i tuoi hobby?" onNext={onNext} onBack={onBack} onSkip={onSkip} canNext>
      <Typography variant="caption" sx={{ color: "var(--color-text-2)", mb: 1, display: "block" }}>
        Puoi selezionare più opzioni
      </Typography>
      <Box sx={{ display: "flex", flexWrap: "wrap", gap: 1 }}>
        {options.map((o) => (
          <ToggleButton
            key={o.value}
            value={o.value}
            selected={value.includes(o.value)}
            onChange={() => toggle(o.value)}
            sx={toggleBtnSx}
          >
            {o.label}
          </ToggleButton>
        ))}
      </Box>
    </StepWrapper>
  );
}

function BudgetStep({
  value,
  onChange,
  onNext,
  onBack,
  onSkip,
}: {
  value: string;
  onChange: (v: string) => void;
  onNext: () => void;
  onBack: () => void;
  onSkip: () => void;
}) {
  return (
    <StepWrapper title="Budget mensile indicativo" onNext={onNext} onBack={onBack} onSkip={onSkip} canNext>
      <Typography variant="caption" sx={{ color: "var(--color-text-2)", mb: 2, display: "block" }}>
        Quant&apos;è la tua spesa mensile tipica? Puoi lasciarlo vuoto.
      </Typography>
      <TextField
        type="number"
        label="Budget (€)"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        inputProps={{ min: 0 }}
        fullWidth
        size="small"
      />
    </StepWrapper>
  );
}

function NotificationsStep({
  enabled,
  time,
  onEnabledChange,
  onTimeChange,
  onNext,
  onBack,
  onSkip,
}: {
  enabled: boolean;
  time: string;
  onEnabledChange: (v: boolean) => void;
  onTimeChange: (v: string) => void;
  onNext: () => void;
  onBack: () => void;
  onSkip: () => void;
}) {
  return (
    <StepWrapper title="Riepilogo giornaliero" onNext={onNext} onBack={onBack} onSkip={onSkip} canNext>
      <FormControlLabel
        control={
          <Switch checked={enabled} onChange={(e) => onEnabledChange(e.target.checked)} />
        }
        label="Ricevi un riepilogo giornaliero"
        sx={{ mb: 2 }}
      />
      {enabled && (
        <TextField
          type="time"
          label="Orario notifica"
          value={time}
          onChange={(e) => onTimeChange(e.target.value)}
          size="small"
          sx={{ maxWidth: 160 }}
        />
      )}
    </StepWrapper>
  );
}

function CategoryReviewStep({
  lifestyle,
  selected,
  onToggle,
  onNext,
  onBack,
}: {
  lifestyle: Lifestyle;
  selected: Set<string>;
  onToggle: (cat: string) => void;
  onNext: (cats: string[]) => void;
  onBack: () => void;
}) {
  const [categories, setCategories] = useState<string[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    buildHeaders()
      .then((headers) => fetch("/api/onboarding/generate-categories", {
        method: "POST",
        headers: { ...headers, "Content-Type": "application/json" },
        credentials: "same-origin",
        body: JSON.stringify({ lifestyle }),
      }))
      .then((r) => r.json())
      .then((data) => {
        if (cancelled) return;
        const cats: string[] = data.categories ?? [];
        setCategories(cats);
        // Pre-seleziona tutte
        cats.forEach((c) => {
          if (!selected.has(c)) onToggle(c);
        });
      })
      .catch(() => {
        if (!cancelled) setCategories([]);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => { cancelled = true; };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const selectedList = categories.filter((c) => selected.has(c));

  return (
    <Box>
      <Typography variant="h6" fontWeight={600} sx={{ mb: 1 }}>
        Le tue categorie di spesa
      </Typography>
      <Typography variant="body2" sx={{ color: "var(--color-text-2)", mb: 2 }}>
        Ho pensato a queste categorie per te. Rimuovi quelle che non ti servono.
      </Typography>

      {loading ? (
        <Box sx={{ display: "flex", flexWrap: "wrap", gap: 1 }}>
          {Array.from({ length: 12 }).map((_, i) => (
            <Skeleton key={i} variant="rounded" width={100 + (i % 3) * 30} height={32} />
          ))}
        </Box>
      ) : (
        <Box sx={{ display: "flex", flexWrap: "wrap", gap: 1, mb: 3 }}>
          {categories.map((cat) => (
            <Chip
              key={cat}
              label={cat}
              variant={selected.has(cat) ? "filled" : "outlined"}
              color={selected.has(cat) ? "primary" : "default"}
              onClick={() => onToggle(cat)}
              sx={{ cursor: "pointer", fontWeight: selected.has(cat) ? 600 : 400 }}
            />
          ))}
        </Box>
      )}

      <Box sx={{ display: "flex", gap: 1, mt: 2 }}>
        <Button variant="outlined" onClick={onBack} sx={{ flex: "0 0 auto" }}>
          ↩ Indietro
        </Button>
        <Button
          variant="contained"
          onClick={() => onNext(selectedList)}
          disabled={loading || selectedList.length === 0}
          sx={{ ...primaryBtnSx, flex: 1 }}
        >
          Continua con {selectedList.length} categorie
        </Button>
      </Box>
    </Box>
  );
}

function ConfirmStep({
  state,
  onConfirm,
  onBack,
  loading,
}: {
  state: WizardState;
  onConfirm: () => void;
  onBack: () => void;
  loading: boolean;
}) {
  const rows = [
    { label: "Lingua", value: state.language === "it" ? "🇮🇹 Italiano" : "🇬🇧 English" },
    { label: "Valuta", value: state.currency },
    { label: "Timezone", value: state.timezone },
    ...(state.lifestyle.transport ? [{ label: "Trasporti", value: state.lifestyle.transport }] : []),
    ...(state.lifestyle.dining ? [{ label: "Dining", value: state.lifestyle.dining }] : []),
    ...(state.lifestyle.hobbies?.length ? [{ label: "Hobby", value: state.lifestyle.hobbies.join(", ") }] : []),
    ...(state.budget ? [{ label: "Budget", value: `€ ${state.budget}` }] : []),
    { label: "Categorie", value: `${state.selectedCategories.size} selezionate` },
  ];

  return (
    <Box>
      <Typography variant="h6" fontWeight={600} sx={{ mb: 2 }}>
        Tutto pronto! 🎉
      </Typography>
      <Box sx={{ mb: 3, display: "flex", flexDirection: "column", gap: 1 }}>
        {rows.map((r) => (
          <Box key={r.label} sx={{ display: "flex", justifyContent: "space-between", py: 0.5, borderBottom: "1px solid var(--color-border)" }}>
            <Typography variant="body2" sx={{ color: "var(--color-text-2)" }}>{r.label}</Typography>
            <Typography variant="body2" fontWeight={500}>{r.value}</Typography>
          </Box>
        ))}
      </Box>
      <Box sx={{ display: "flex", gap: 1 }}>
        <Button variant="outlined" onClick={onBack} disabled={loading}>
          ↩ Indietro
        </Button>
        <Button
          variant="contained"
          onClick={onConfirm}
          disabled={loading}
          sx={{ ...primaryBtnSx, flex: 1 }}
        >
          {loading ? <CircularProgress size={20} sx={{ color: "#fff" }} /> : "🚀 Inizia!"}
        </Button>
      </Box>
    </Box>
  );
}

// ─── Shared sub-components ────────────────────────────────────────────────────

function StepWrapper({
  title,
  required,
  children,
  onNext,
  onBack,
  onSkip,
  canNext,
}: {
  title: string;
  required?: boolean;
  children: React.ReactNode;
  onNext: () => void;
  onBack: () => void;
  onSkip?: () => void;
  canNext: boolean;
}) {
  return (
    <Box>
      <Typography variant="h6" fontWeight={600} sx={{ mb: 0.5 }}>
        {title}
        {required && <Typography component="span" sx={{ color: "var(--color-primary)", ml: 0.5, fontSize: 12 }}>★</Typography>}
      </Typography>
      <Box sx={{ mb: 3 }}>{children}</Box>
      <Box sx={{ display: "flex", gap: 1, flexWrap: "wrap" }}>
        <Button variant="outlined" onClick={onBack} size="small">↩ Indietro</Button>
        {onSkip && (
          <Button variant="text" onClick={onSkip} size="small" sx={{ color: "var(--color-text-2)" }}>
            ⏭ Salta
          </Button>
        )}
        <Button
          variant="contained"
          onClick={onNext}
          disabled={!canNext}
          sx={{ ...primaryBtnSx, ml: "auto" }}
        >
          Avanti →
        </Button>
      </Box>
    </Box>
  );
}

// ─── Styles ───────────────────────────────────────────────────────────────────

const primaryBtnSx = {
  bgcolor: "var(--color-primary)",
  "&:hover": { bgcolor: "var(--color-primary-dark)" },
  textTransform: "none",
  borderRadius: 2,
  fontWeight: 600,
};

const toggleBtnSx = {
  border: "1px solid var(--color-border) !important",
  borderRadius: "8px !important",
  px: 2,
  textTransform: "none",
  fontWeight: 500,
  "&.Mui-selected": {
    bgcolor: "var(--color-primary-light)",
    borderColor: "var(--color-primary) !important",
    color: "var(--color-primary)",
    fontWeight: 700,
  },
};

// ─── Step definitions (ordered) ───────────────────────────────────────────────

const STEP_NAMES = [
  "welcome", "language", "currency", "timezone",
  "transport", "dining", "hobbies", "budget",
  "notifications", "categories", "confirm",
] as const;

const TOTAL_VISIBLE = 10; // step 0 (welcome) non conta nella progress bar

// ─── Main wizard ──────────────────────────────────────────────────────────────

export default function OnboardingPage() {
  const router = useRouter();
  const [step, setStep] = useState(0);
  const [submitting, setSubmitting] = useState(false);
  const [animDir, setAnimDir] = useState<"forward" | "back">("forward");

  const [state, setState] = useState<WizardState>({
    language: "it",
    currency: "EUR",
    timezone: "Europe/Rome",
    lifestyle: {},
    budget: "",
    notificationsEnabled: true,
    notificationTime: "08:00",
    categories: [],
    selectedCategories: new Set(),
  });

  const update = useCallback((partial: Partial<WizardState>) => {
    setState((prev) => ({ ...prev, ...partial }));
  }, []);

  const saveStep = useCallback(async (stepName: string, data: Record<string, unknown>) => {
    try {
      await fetch("/api/onboarding/step", {
        method: "POST",
        headers: { ...(await buildHeaders()), "Content-Type": "application/json" },
        credentials: "same-origin",
        body: JSON.stringify({ step: stepName, data }),
      });
    } catch {
      // non-bloccante
    }
  }, []);

  const goNext = useCallback(
    (stepName: string, data: Record<string, unknown> = {}) => {
      setAnimDir("forward");
      if (stepName !== "welcome") saveStep(stepName, data);
      setStep((s) => s + 1);
    },
    [saveStep]
  );

  const goBack = useCallback(() => {
    setAnimDir("back");
    setStep((s) => Math.max(0, s - 1));
  }, []);

  const toggleCategory = useCallback((cat: string) => {
    setState((prev) => {
      const next = new Set(prev.selectedCategories);
      next.has(cat) ? next.delete(cat) : next.add(cat);
      return { ...prev, selectedCategories: next };
    });
  }, []);

  const handleComplete = useCallback(async () => {
    setSubmitting(true);
    try {
      await fetch("/api/onboarding/complete", {
        method: "POST",
        headers: { ...(await buildHeaders()), "Content-Type": "application/json" },
        credentials: "same-origin",
        body: JSON.stringify({
          selected_categories: [...state.selectedCategories],
        }),
      });
      router.push("/chat");
    } catch {
      setSubmitting(false);
    }
  }, [state.selectedCategories, router]);

  // Check if already completed
  useEffect(() => {
    buildHeaders()
      .then((headers) => fetch("/api/onboarding/status", { headers, credentials: "same-origin" }))
      .then((r) => r.json())
      .then((data) => {
        if (data.onboarding_completed_at) router.replace("/chat");
        if (data.preferred_language) update({ language: data.preferred_language });
        if (data.currency) update({ currency: data.currency });
        if (data.timezone) update({ timezone: data.timezone });
      })
      .catch(() => {});
  }, [router, update]);

  const visibleStep = step; // step 0 = welcome, 1..10 = actual steps
  const progressValue = step === 0 ? 0 : (step / TOTAL_VISIBLE) * 100;

  return (
    <Box
      sx={{
        minHeight: "100vh",
        bgcolor: "var(--color-base)",
        display: "flex",
        alignItems: "flex-start",
        justifyContent: "center",
        px: 2,
        py: 4,
      }}
    >
      <Box
        sx={{
          width: "100%",
          maxWidth: 480,
          bgcolor: "var(--color-surface)",
          borderRadius: 3,
          p: { xs: 3, sm: 4 },
          boxShadow: "0 2px 16px rgba(0,0,0,0.07)",
        }}
      >
        {/* Header */}
        {step > 0 && (
          <Box sx={{ mb: 3 }}>
            <Typography variant="caption" sx={{ color: "var(--color-text-2)" }}>
              Step {step} di {TOTAL_VISIBLE}
            </Typography>
            <LinearProgress
              variant="determinate"
              value={progressValue}
              sx={{
                mt: 0.5,
                height: 6,
                borderRadius: 3,
                bgcolor: "var(--color-surface-2)",
                "& .MuiLinearProgress-bar": { bgcolor: "var(--color-primary)" },
              }}
            />
          </Box>
        )}

        {/* Step content with slide animation */}
        <Box
          key={`${step}-${animDir}`}
          sx={{
            animation: `${animDir === "forward" ? "slideInRight" : "slideInLeft"} 0.2s ease-out`,
            "@keyframes slideInRight": {
              from: { opacity: 0, transform: "translateX(20px)" },
              to: { opacity: 1, transform: "translateX(0)" },
            },
            "@keyframes slideInLeft": {
              from: { opacity: 0, transform: "translateX(-20px)" },
              to: { opacity: 1, transform: "translateX(0)" },
            },
          }}
        >
          {step === 0 && <WelcomeStep onNext={() => goNext("welcome")} />}

          {step === 1 && (
            <LanguageStep
              value={state.language}
              onChange={(v) => update({ language: v })}
              onNext={() => goNext("language", { language: state.language })}
              onBack={goBack}
            />
          )}

          {step === 2 && (
            <CurrencyStep
              value={state.currency}
              onChange={(v) => update({ currency: v })}
              onNext={() => goNext("currency", { currency: state.currency })}
              onBack={goBack}
            />
          )}

          {step === 3 && (
            <TimezoneStep
              value={state.timezone}
              onChange={(v) => update({ timezone: v })}
              onNext={() => goNext("timezone", { timezone: state.timezone })}
              onBack={goBack}
            />
          )}

          {step === 4 && (
            <TransportStep
              value={state.lifestyle.transport ?? ""}
              onChange={(v) => update({ lifestyle: { ...state.lifestyle, transport: v } })}
              onNext={() => goNext("transport", { transport: state.lifestyle.transport })}
              onBack={goBack}
              onSkip={() => goNext("transport_skipped")}
            />
          )}

          {step === 5 && (
            <DiningStep
              value={state.lifestyle.dining ?? ""}
              onChange={(v) => update({ lifestyle: { ...state.lifestyle, dining: v } })}
              onNext={() => goNext("dining", { dining: state.lifestyle.dining })}
              onBack={goBack}
              onSkip={() => goNext("dining_skipped")}
            />
          )}

          {step === 6 && (
            <HobbiesStep
              value={state.lifestyle.hobbies ?? []}
              onChange={(v) => update({ lifestyle: { ...state.lifestyle, hobbies: v } })}
              onNext={() => goNext("hobbies", { hobbies: state.lifestyle.hobbies })}
              onBack={goBack}
              onSkip={() => goNext("hobbies_skipped")}
            />
          )}

          {step === 7 && (
            <BudgetStep
              value={state.budget}
              onChange={(v) => update({ budget: v })}
              onNext={() =>
                goNext("budget", { budget: state.budget ? parseFloat(state.budget) : null })
              }
              onBack={goBack}
              onSkip={() => goNext("budget_skipped")}
            />
          )}

          {step === 8 && (
            <NotificationsStep
              enabled={state.notificationsEnabled}
              time={state.notificationTime}
              onEnabledChange={(v) => update({ notificationsEnabled: v })}
              onTimeChange={(v) => update({ notificationTime: v })}
              onNext={() =>
                goNext("notifications", {
                  notifications_enabled: state.notificationsEnabled,
                  notification_time: state.notificationTime,
                })
              }
              onBack={goBack}
              onSkip={() => goNext("notifications_skipped")}
            />
          )}

          {step === 9 && (
            <CategoryReviewStep
              lifestyle={state.lifestyle}
              selected={state.selectedCategories}
              onToggle={toggleCategory}
              onNext={(cats) => {
                update({ categories: cats });
                setStep(10);
              }}
              onBack={goBack}
            />
          )}

          {step === 10 && (
            <ConfirmStep
              state={state}
              onConfirm={handleComplete}
              onBack={goBack}
              loading={submitting}
            />
          )}

          {/* Fallback guard */}
          {visibleStep > 10 && null}
        </Box>
      </Box>
    </Box>
  );
}
