"use client";

import { useMemo, useState } from "react";
import {
  Box, Card, CardContent, Typography, TextField, Slider, ToggleButton,
  ToggleButtonGroup, Accordion, AccordionSummary, AccordionDetails, Divider, Button,
} from "@mui/material";
import { ChevronDown, Landmark } from "lucide-react";
import { useTranslations } from "next-intl";
import NextLink from "next/link";
import Image from "next/image";
import { Link } from "@/i18n/navigation";
import { calculateInstallment, calculateTaeg } from "@/lib/loanCalculator";

// Chiave localStorage con cui il wizard autenticato (/mutuo in dashboard) preleva
// i parametri calcolati qui, alla prima apertura dopo la registrazione. La query
// string non sopravvive al redirect di /register (pagina Flask, non Next), quindi
// il passaggio dati avviene così invece che per URL.
const HANDOFF_KEY = "expensum_mutuo_calc_handoff";

function fmtCurrency(n: number): string {
  return n.toLocaleString("it-IT", { style: "currency", currency: "EUR" });
}

export default function MutuoCalculatorClient() {
  const t = useTranslations("MutuoCalculator");

  const [principal, setPrincipal] = useState(200000);
  const [durationYears, setDurationYears] = useState(25);
  const [rateType, setRateType] = useState<"fisso" | "variabile">("fisso");
  const [tan, setTan] = useState(3.0);
  const [originationFee, setOriginationFee] = useState(0);
  const [monthlyFee, setMonthlyFee] = useState(0);

  const durationMonths = durationYears * 12;

  const result = useMemo(() => {
    if (principal <= 0 || durationMonths <= 0 || tan < 0) return null;
    const installment = calculateInstallment(principal, tan, durationMonths);
    const taeg = calculateTaeg(principal, tan, durationMonths, originationFee, monthlyFee);
    const totalInterest = installment * durationMonths - principal;
    return { installment, taeg, totalInterest };
  }, [principal, durationMonths, tan, originationFee, monthlyFee]);

  const handleContinue = () => {
    if (typeof window !== "undefined") {
      window.localStorage.setItem(
        HANDOFF_KEY,
        JSON.stringify({ principal, durationMonths, rateType, tan, originationFee, monthlyFee })
      );
    }
  };

  return (
    <Box sx={{ minHeight: "100vh", display: "flex", flexDirection: "column" }}>
      <Box
        sx={{
          display: "flex", justifyContent: "space-between", alignItems: "center",
          px: { xs: 2, md: 4 }, py: { xs: 1.25, md: 1.5 },
          borderBottom: 1, borderColor: "divider", bgcolor: "background.paper",
          position: "sticky", top: 0, zIndex: 10,
        }}
      >
        <Link href="/" style={{ display: "flex", alignItems: "center", gap: 8, textDecoration: "none" }}>
          <Image src="/logo-expensum-icon.png" alt="Expensum" width={28} height={28} />
          <Typography component="span" sx={{ fontSize: "17px", fontWeight: 300, letterSpacing: "0.015em", color: "text.primary" }}>
            Expensum
          </Typography>
        </Link>
        <Link href="/" style={{ display: "inline-flex", alignItems: "center", minHeight: 44, padding: "0 8px", textDecoration: "none", color: "inherit" }}>
          <Typography sx={{ color: "text.secondary", fontSize: "0.875rem" }}>{t("backToSite")}</Typography>
        </Link>
      </Box>

      <Box sx={{ p: { xs: 2, md: 4 }, maxWidth: 820, mx: "auto", flex: 1, width: "100%" }}>
        <Box sx={{ mb: 4, textAlign: "center" }}>
          <Typography
            component="h1"
            variant="h4"
            fontWeight={300}
            color="primary.main"
            gutterBottom
            sx={{ display: "flex", alignItems: "center", justifyContent: "center", gap: 1.5 }}
          >
            <Landmark size={30} strokeWidth={1.5} aria-hidden="true" />
            {t("title")}
          </Typography>
          <Typography color="text.secondary">{t("intro")}</Typography>
        </Box>

        <Card sx={{ borderRadius: 4, mb: 3 }}>
          <CardContent sx={{ display: "flex", flexDirection: "column", gap: 3 }}>
            <TextField
              label={t("fields.principal")}
              type="number"
              value={principal}
              onChange={(e) => setPrincipal(Number(e.target.value) || 0)}
              fullWidth
            />

            <Box>
              <Typography variant="body2" color="text.secondary" gutterBottom>
                {t("fields.duration", { years: durationYears })}
              </Typography>
              <Slider
                aria-label={t("fields.duration", { years: durationYears })}
                value={durationYears}
                onChange={(_, v) => setDurationYears(v as number)}
                min={1}
                max={35}
                step={1}
                valueLabelDisplay="auto"
              />
            </Box>

            <Box>
              <Typography variant="body2" color="text.secondary" gutterBottom>
                {t("fields.rateType")}
              </Typography>
              <ToggleButtonGroup
                exclusive
                value={rateType}
                onChange={(_, v) => v && setRateType(v)}
                fullWidth
              >
                <ToggleButton value="fisso">{t("fields.rateTypeFixed")}</ToggleButton>
                <ToggleButton value="variabile">{t("fields.rateTypeVariable")}</ToggleButton>
              </ToggleButtonGroup>
            </Box>

            <TextField
              label={t("fields.tan")}
              type="number"
              value={tan}
              onChange={(e) => setTan(Number(e.target.value) || 0)}
              slotProps={{ htmlInput: { step: 0.01 } }}
              helperText={t("fields.tanHelper")}
              fullWidth
            />

            <Accordion sx={{ bgcolor: "transparent", "&:before": { display: "none" } }}>
              <AccordionSummary expandIcon={<ChevronDown size={18} strokeWidth={1.75} aria-hidden="true" />}>
                <Typography variant="body2">{t("fields.accessoryCostsToggle")}</Typography>
              </AccordionSummary>
              <AccordionDetails sx={{ display: "flex", flexDirection: "column", gap: 2 }}>
                <TextField
                  label={t("fields.originationFee")}
                  type="number"
                  value={originationFee}
                  onChange={(e) => setOriginationFee(Number(e.target.value) || 0)}
                  helperText={t("fields.originationFeeHelper")}
                  fullWidth
                />
                <TextField
                  label={t("fields.monthlyFee")}
                  type="number"
                  value={monthlyFee}
                  onChange={(e) => setMonthlyFee(Number(e.target.value) || 0)}
                  helperText={t("fields.monthlyFeeHelper")}
                  fullWidth
                />
              </AccordionDetails>
            </Accordion>
          </CardContent>
        </Card>

        {result && (
          <Card sx={{ borderRadius: 4, mb: 3, borderColor: "primary.main", minWidth: 0 }}>
            <CardContent>
              <Typography variant="h6" fontWeight={500} gutterBottom>
                {t("results.title")}
              </Typography>
              <Divider sx={{ my: 1.5 }} />
              <Box sx={{ display: "flex", flexDirection: { xs: "column", sm: "row" }, alignItems: { xs: "flex-start", sm: "center" }, justifyContent: "space-between", gap: 0.5, mb: 1.5 }}>
                <Typography color="text.secondary">{t("results.installment")}</Typography>
                <Typography variant="h6" color="primary.main" sx={{ overflowWrap: "anywhere" }}>{fmtCurrency(result.installment)}</Typography>
              </Box>
              <Box sx={{ display: "flex", flexDirection: { xs: "column", sm: "row" }, alignItems: { xs: "flex-start", sm: "center" }, justifyContent: "space-between", gap: 0.5, mb: 1.5 }}>
                <Typography color="text.secondary">{t("results.taeg")}</Typography>
                <Typography sx={{ overflowWrap: "anywhere" }}>{result.taeg.toFixed(2)}%</Typography>
              </Box>
              <Box sx={{ display: "flex", flexDirection: { xs: "column", sm: "row" }, alignItems: { xs: "flex-start", sm: "center" }, justifyContent: "space-between", gap: 0.5 }}>
                <Typography color="text.secondary">{t("results.totalInterest")}</Typography>
                <Typography sx={{ overflowWrap: "anywhere" }}>{fmtCurrency(result.totalInterest)}</Typography>
              </Box>
              <Typography variant="caption" color="text.secondary" sx={{ display: "block", mt: 2 }}>
                {t("results.disclaimer")}
              </Typography>
            </CardContent>
          </Card>
        )}

        <Box sx={{ textAlign: "center", width: "100%" }}>
          <Button
            component={NextLink}
            href="/register"
            onClick={handleContinue}
            variant="contained"
            size="large"
            sx={{ width: { xs: "100%", sm: "auto" }, minHeight: { xs: 44, sm: 48 } }}
          >
            {t("cta")}
          </Button>
        </Box>
      </Box>
    </Box>
  );
}
