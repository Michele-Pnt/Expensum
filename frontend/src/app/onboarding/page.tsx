"use client";

import { useState, useEffect, useCallback } from "react";
import { useRouter } from "next/navigation";
import { getCsrfToken } from "@/lib/csrf";
import { trackOnboardingStepCompleted, trackOnboardingCompleted, trackReferralLinkGenerated } from "@/lib/analytics";
import {
  Box,
  Typography,
  Button,
  CircularProgress,
  LinearProgress,
  TextField,
  ToggleButton,
  ToggleButtonGroup,
  Switch,
  FormControlLabel,
} from "@mui/material";

// ─── Types ────────────────────────────────────────────────────────────────────

interface WizardState {
  language: string;
  currency: string;
  timezone: string;
  hobbies: string[];
  notificationsEnabled: boolean;
  notificationTime: string;
}

function detectLocaleDefaults(): { timezone: string; currency: string } {
  const tz = Intl.DateTimeFormat().resolvedOptions().timeZone || "Europe/Rome";
  const lang = typeof navigator !== "undefined" ? navigator.language : "it";
  const currency = lang.startsWith("en-US") ? "USD"
    : lang.startsWith("en-GB") ? "GBP"
    : lang.startsWith("de") || lang.startsWith("fr") || lang.startsWith("es") || lang.startsWith("it") ? "EUR"
    : "EUR";
  return { timezone: tz, currency };
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
        👋 Benvenuto su Expensum!
      </Typography>
      <Typography variant="body1" sx={{ mb: 4, color: "var(--color-text-2)", maxWidth: 340, mx: "auto" }}>
        In meno di 2 minuti personalizzeremo il tuo spazio in base al tuo stile di vita.
      </Typography>
      <Button variant="contained" size="large" onClick={onNext} sx={primaryBtnSx}>
        Iniziamo 🚀
      </Button>
    </Box>
  );
}

function AgeGateStep({
  onConfirm,
  loading,
}: {
  onConfirm: () => void;
  loading: boolean;
}) {
  const [blocked, setBlocked] = useState(false);

  if (blocked) {
    return (
      <Box sx={{ textAlign: "center", py: 4 }}>
        <Typography variant="h6" fontWeight={600} sx={{ mb: 2 }}>
          ⚠️ Servizio riservato ai maggiorenni
        </Typography>
        <Typography variant="body2" sx={{ color: "var(--color-text-2)" }}>
          Expensum è disponibile solo per utenti con 18 anni o più (D.Lgs. 101/2018).
        </Typography>
      </Box>
    );
  }

  return (
    <Box>
      <Typography variant="h6" fontWeight={600} sx={{ mb: 1 }}>
        🔞 Verifica età
      </Typography>
      <Typography variant="body2" sx={{ color: "var(--color-text-2)", mb: 3 }}>
        Expensum è riservato a utenti maggiorenni (18+), in conformità al D.Lgs. 101/2018
        e per garantire la capacità contrattuale per il piano Pro.
      </Typography>
      <Box sx={{ display: "flex", flexDirection: "column", gap: 2 }}>
        <Button
          variant="contained"
          size="large"
          onClick={onConfirm}
          disabled={loading}
          sx={primaryBtnSx}
        >
          {loading ? <CircularProgress size={20} sx={{ color: "#fff" }} /> : "✅ Sì, ho 18 anni o più"}
        </Button>
        <Button
          variant="outlined"
          size="large"
          onClick={() => setBlocked(true)}
          disabled={loading}
          sx={{ textTransform: "none", borderRadius: 2 }}
        >
          ❌ Sono minorenne
        </Button>
      </Box>
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

const LIFESTYLE_OPTIONS = [
  { value: "palestra", label: "💪 Sport / Palestra" },
  { value: "streaming", label: "📺 Streaming / Gaming" },
  { value: "viaggi", label: "✈️ Viaggi" },
  { value: "cultura", label: "🎭 Cinema / Cultura" },
  { value: "tech", label: "💻 Tech / Elettronica" },
  { value: "animali", label: "🐾 Animali domestici" },
  { value: "cucina", label: "🍳 Cibo / Gourmet" },
  { value: "famiglia", label: "👶 Famiglia / Figli" },
  { value: "moda", label: "👗 Moda / Beauty" },
];

function LifestyleStep({
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
  const toggle = (v: string) => {
    onChange(value.includes(v) ? value.filter((x) => x !== v) : [...value, v]);
  };
  return (
    <StepWrapper title="Il tuo stile di vita" onNext={onNext} onBack={onBack} onSkip={onSkip} canNext>
      <Typography variant="caption" sx={{ color: "var(--color-text-2)", mb: 1, display: "block" }}>
        Seleziona uno o più interessi. Useremo questa informazione per personalizzare le categorie di spesa.
      </Typography>
      <Box sx={{ display: "flex", flexWrap: "wrap", gap: 1 }}>
        {LIFESTYLE_OPTIONS.map((o) => (
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
  const hobbyLabels = state.hobbies.map(
    (h) => LIFESTYLE_OPTIONS.find((o) => o.value === h)?.label ?? h
  );

  const rows = [
    { label: "Lingua", value: state.language === "it" ? "🇮🇹 Italiano" : "🇬🇧 English" },
    { label: "Valuta", value: `${state.currency} (auto-rilevata)` },
    { label: "Timezone", value: `${state.timezone} (auto-rilevata)` },
    ...(hobbyLabels.length ? [{ label: "Interessi", value: hobbyLabels.join(", ") }] : []),
    {
      label: "Notifiche",
      value: state.notificationsEnabled ? `✅ Alle ${state.notificationTime}` : "🔕 Disabilitate",
    },
  ];

  return (
    <Box>
      <Typography variant="h6" fontWeight={600} sx={{ mb: 2 }}>
        Tutto pronto! 🎉
      </Typography>
      <Box sx={{ mb: 3, display: "flex", flexDirection: "column", gap: 1 }}>
        {rows.map((r) => (
          <Box
            key={r.label}
            sx={{
              display: "flex",
              justifyContent: "space-between",
              py: 0.5,
              borderBottom: "1px solid var(--color-border)",
            }}
          >
            <Typography variant="body2" sx={{ color: "var(--color-text-2)" }}>
              {r.label}
            </Typography>
            <Typography variant="body2" fontWeight={500} sx={{ textAlign: "right", ml: 2 }}>
              {r.value}
            </Typography>
          </Box>
        ))}
      </Box>
      <Typography variant="caption" sx={{ color: "var(--color-text-2)", display: "block", mb: 2 }}>
        Le categorie di spesa verranno create automaticamente in base ai tuoi interessi.
      </Typography>
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

interface ReferralLinkData {
  link: string;
  referred_count: number;
  lifetime_founder_guaranteed: boolean;
}

function InviteStep({ onContinue }: { onContinue: () => void }) {
  const [data, setData] = useState<ReferralLinkData | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    buildHeaders()
      .then((headers) => fetch("/api/referral/link", { headers, credentials: "same-origin" }))
      .then((r) => (r.ok ? r.json() : null))
      .then((json) => {
        if (!cancelled && json) {
          setData(json);
          trackReferralLinkGenerated();
        }
      })
      .catch(() => {})
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const shareText = data
    ? `Sto usando Expensum per tenere sotto controllo le spese, provalo anche tu: ${data.link}`
    : "";
  const whatsappUrl = `https://wa.me/?text=${encodeURIComponent(shareText)}`;

  return (
    <Box sx={{ textAlign: "center", py: 2 }}>
      <Typography variant="h5" fontWeight={700} sx={{ mb: 1 }}>
        Fatto! 🎉
      </Typography>
      <Typography variant="body1" sx={{ mb: 3, color: "var(--color-text-2)" }}>
        Invita 3 amici con il tuo link personale: ognuno di voi riceve 2 mesi di Pro
        gratis, e tu sblocchi un posto garantito nell&apos;offerta Lifetime Founder.
      </Typography>

      {loading ? (
        <CircularProgress size={24} sx={{ mb: 3 }} />
      ) : data ? (
        <>
          <Box
            sx={{
              mb: 3, p: 1.5, borderRadius: 2, bgcolor: "var(--color-surface-2)",
              wordBreak: "break-all", fontSize: 14, color: "var(--color-text-2)",
            }}
          >
            {data.link}
          </Box>
          <Button
            variant="contained"
            size="large"
            fullWidth
            href={whatsappUrl}
            target="_blank"
            rel="noopener noreferrer"
            sx={{ ...primaryBtnSx, bgcolor: "#25D366", mb: 1.5, "&:hover": { bgcolor: "#1ebe57" } }}
          >
            📲 Condividi su WhatsApp
          </Button>
          <Typography variant="caption" sx={{ display: "block", mb: 1, color: "var(--color-text-2)" }}>
            {data.referred_count > 0
              ? `Hai già invitato ${data.referred_count} ${data.referred_count === 1 ? "persona" : "persone"}.`
              : "Nessun invito ancora — condividi il link per iniziare."}
          </Typography>
          <Typography variant="caption" sx={{ display: "block", mb: 3, color: "var(--color-text-2)" }}>
            Ritrovi sempre il link nella tab &quot;Invita amici&quot;.
          </Typography>
        </>
      ) : (
        <Typography variant="body2" sx={{ mb: 3, color: "var(--color-text-2)" }}>
          Il link personale sarà disponibile a breve nella tab &quot;Invita amici&quot;.
        </Typography>
      )}

      <Button variant="text" onClick={onContinue} sx={{ textTransform: "none" }}>
        Vai alla dashboard →
      </Button>
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
        {required && (
          <Typography component="span" sx={{ color: "var(--color-primary)", ml: 0.5, fontSize: 12 }}>
            ★
          </Typography>
        )}
      </Typography>
      <Box sx={{ mb: 3 }}>{children}</Box>
      <Box sx={{ display: "flex", gap: 1, flexWrap: "wrap" }}>
        <Button variant="outlined" onClick={onBack} size="small">
          ↩ Indietro
        </Button>
        {onSkip && (
          <Button
            variant="text"
            onClick={onSkip}
            size="small"
            sx={{ color: "var(--color-text-2)" }}
          >
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

// ─── Step definitions ─────────────────────────────────────────────────────────
// step 0 = welcome        (non conta nel progress)
// step 1 = age_gate       (visible 1/5)
// step 2 = language       (visible 2/5)
// step 3 = lifestyle      (visible 3/5)
// step 4 = notifications  (visible 4/5)
// step 5 = confirm        (visible 5/5)
// step 6 = aha-moment     (no progress bar — step finale)

const TOTAL_VISIBLE = 5;

// ─── Main wizard ──────────────────────────────────────────────────────────────

export default function OnboardingPage() {
  const router = useRouter();
  const [step, setStep] = useState(0);
  const [submitting, setSubmitting] = useState(false);
  const [ageLoading, setAgeLoading] = useState(false);
  const [animDir, setAnimDir] = useState<"forward" | "back">("forward");

  const { timezone: detectedTz, currency: detectedCurrency } = detectLocaleDefaults();

  const [state, setState] = useState<WizardState>({
    language: "it",
    currency: detectedCurrency,
    timezone: detectedTz,
    hobbies: [],
    notificationsEnabled: true,
    notificationTime: "08:00",
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
      if (stepName !== "welcome") {
        saveStep(stepName, data);
        trackOnboardingStepCompleted(stepName, step + 1);
      }
      setStep((s) => s + 1);
    },
    [saveStep, step]
  );

  const goBack = useCallback(() => {
    setAnimDir("back");
    setStep((s) => Math.max(0, s - 1));
  }, []);

  const handleAgeConfirm = useCallback(async () => {
    setAgeLoading(true);
    try {
      const headers = await buildHeaders();
      await fetch("/api/onboarding/age-confirm", {
        method: "POST",
        headers: { ...headers, "Content-Type": "application/json" },
        credentials: "same-origin",
        body: JSON.stringify({ confirmed: true }),
      });
      goNext("age_gate", { confirmed: true });
    } catch {
      // procedi comunque — il log verrà riscritto al complete
      goNext("age_gate", { confirmed: true });
    } finally {
      setAgeLoading(false);
    }
  }, [goNext]);

  const handleComplete = useCallback(async () => {
    setSubmitting(true);
    try {
      const headers = await buildHeaders();
      await fetch("/api/onboarding/complete", {
        method: "POST",
        headers: { ...(headers as Record<string, string>), "Content-Type": "application/json" },
        credentials: "same-origin",
        body: JSON.stringify({
          language: state.language,
          currency: state.currency,
          timezone: state.timezone,
          hobbies: state.hobbies,
          notifications_enabled: state.notificationsEnabled,
          notification_time: state.notificationsEnabled ? state.notificationTime : null,
        }),
      });
      trackOnboardingCompleted();
      // Carica demo data in background (fire-and-forget)
      fetch("/api/demo/load", {
        method: "POST",
        headers: headers as Record<string, string>,
        credentials: "same-origin",
      }).catch(() => {});
      // Setta flag tour + demo; rimuove "done" per chi si ri-registra
      try {
        localStorage.removeItem("expensum_tour_done");
        localStorage.removeItem("expensum_tour_step");
        localStorage.setItem("expensum_tour_pending", "true");
        localStorage.setItem("expensum_demo_active", "true");
      } catch { /* ignore */ }
      // Non reindirizza subito: mostra la schermata di condivisione referral
      // (picco di entusiasmo appena finito il form, prima che si distragga).
      setAnimDir("forward");
      setStep(6);
      setSubmitting(false);
    } catch {
      setSubmitting(false);
    }
  }, [state]);

  const goToChat = useCallback(() => {
    // Hard reload: TourProvider deve rimontarsi su /chat per leggere i flag
    window.location.assign("/chat");
  }, []);

  // Controlla se l'onboarding è già completato
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
        {step > 0 && step <= TOTAL_VISIBLE && (
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
            <AgeGateStep onConfirm={handleAgeConfirm} loading={ageLoading} />
          )}

          {step === 2 && (
            <LanguageStep
              value={state.language}
              onChange={(v) => update({ language: v })}
              onNext={() => goNext("language", { language: state.language })}
              onBack={goBack}
            />
          )}

          {step === 3 && (
            <LifestyleStep
              value={state.hobbies}
              onChange={(v) => update({ hobbies: v })}
              onNext={() => goNext("lifestyle", { hobbies: state.hobbies })}
              onBack={goBack}
              onSkip={() => goNext("lifestyle_skipped")}
            />
          )}

          {step === 4 && (
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

          {step === 5 && (
            <ConfirmStep
              state={state}
              onConfirm={handleComplete}
              onBack={goBack}
              loading={submitting}
            />
          )}

          {step === 6 && <InviteStep onContinue={goToChat} />}

        </Box>
      </Box>
    </Box>
  );
}
