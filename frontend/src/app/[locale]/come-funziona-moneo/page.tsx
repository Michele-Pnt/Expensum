import NextLink from "next/link";
import { Box, Card, CardContent, Chip, Stack, Typography } from "@mui/material";
import { getTranslations, setRequestLocale } from "next-intl/server";
import { routing } from "@/i18n/routing";
import { localeAlternates } from "@/i18n/seo";

export function generateStaticParams() {
  return routing.locales.map((locale) => ({ locale }));
}

export async function generateMetadata({
  params,
}: {
  params: Promise<{ locale: string }>;
}) {
  const { locale } = await params;
  const t = await getTranslations({ locale, namespace: "ComeFunzionaMoneo.meta" });
  return {
    title: t("title"),
    description: t("description"),
    alternates: localeAlternates("/come-funziona-moneo"),
  };
}

type AiModel = {
  name: string;
  purpose: string;
  scope: string;
};

export default async function ComeFunzionaMoneoPage({
  params,
}: {
  params: Promise<{ locale: string }>;
}) {
  const { locale } = await params;
  setRequestLocale(locale);
  const t = await getTranslations("ComeFunzionaMoneo");
  const models = t.raw("models.items") as AiModel[];

  return (
    <Box sx={{ p: { xs: 2, md: 4 }, maxWidth: 980, mx: "auto" }}>
      <Box sx={{ mb: 4 }}>
        <Typography variant="h4" fontWeight={800} color="primary.main" gutterBottom>
          {t("title")}
        </Typography>
        <Typography color="text.secondary">{t("intro")}</Typography>
      </Box>

      <Stack spacing={3}>
        <Card sx={{ borderRadius: 4 }}>
          <CardContent>
            <Typography variant="h6" fontWeight={700} gutterBottom>
              {t("aiDisclosure.title")}
            </Typography>
            <Typography color="text.secondary">{t("aiDisclosure.desc")}</Typography>
          </CardContent>
        </Card>

        <Card sx={{ borderRadius: 4 }}>
          <CardContent>
            <Typography variant="h6" fontWeight={700} gutterBottom>
              {t("models.title")}
            </Typography>
            <Stack spacing={2} sx={{ mt: 1 }}>
              {models.map((model) => (
                <Box key={model.name} sx={{ display: "flex", gap: 2, alignItems: "flex-start" }}>
                  <Chip label={model.scope} size="small" sx={{ mt: 0.5, flexShrink: 0 }} />
                  <Box>
                    <Typography fontWeight={700}>{model.name}</Typography>
                    <Typography color="text.secondary">{model.purpose}</Typography>
                  </Box>
                </Box>
              ))}
            </Stack>
            <Typography color="text.secondary" sx={{ mt: 2 }}>
              {t("models.footnote")}
            </Typography>
          </CardContent>
        </Card>

        <Card sx={{ borderRadius: 4 }}>
          <CardContent>
            <Typography variant="h6" fontWeight={700} gutterBottom>
              {t("limits.title")}
            </Typography>
            <Typography color="text.secondary">{t("limits.desc")}</Typography>
          </CardContent>
        </Card>

        <Card sx={{ borderRadius: 4 }}>
          <CardContent>
            <Typography variant="h6" fontWeight={700} gutterBottom>
              {t("privacy.title")}
            </Typography>
            <Typography color="text.secondary">
              {t("privacy.descBefore")}{" "}
              <NextLink href="/impostazioni/privacy">{t("privacy.link")}</NextLink>.
            </Typography>
          </CardContent>
        </Card>
      </Stack>
    </Box>
  );
}
