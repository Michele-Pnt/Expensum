export const PRODUCT_SCREEN_CONTENT = {
  capture: {
    transaction: {
      name: "Sushi",
      amount: "24,00 €",
      category: "Ristoranti & Fast Food",
      account: "Conto principale",
      date: "Oggi",
    },
  },
  overview: {
    available: "657,20 €",
    spent: "742,80 €",
    delta: "−8%",
    movements: [
      { name: "Sushi", category: "Ristoranti", amount: "−24,00 €" },
      { name: "Affitto", category: "Casa", amount: "−520,00 €" },
      { name: "Stipendio", category: "Entrate", amount: "+1.600,00 €" },
    ],
  },
  goals: {
    items: [
      {
        name: "Weekend a Lisbona",
        type: "Obiettivo di risparmio",
        current: "680,00 €",
        target: "1.000,00 €",
        progress: 68,
        status: "In linea",
        detail: "Mancano 320,00 € per raggiungere l’obiettivo.",
        eta: "15 dicembre 2026",
      },
    ],
  },
  report: {
    items: [
      { type: "Settimanale", date: "31 agosto 2026", status: "Disponibile" },
      { type: "Mensile", date: "1 agosto 2026", status: "Disponibile" },
    ],
  },
} as const;
