/**
 * Colori dei grafici, derivati dal brand kit (dark rebrand 2026-08-08).
 *
 * Il brand kit prescrive per i grafici due soli colori: Platino come neutro e
 * Turchese come accento ("Grafici: lineari e intuitivi, colori Neutro e
 * Accento" / "Grafici lineari in #B0B5B9 con evidenziazioni in #5FC4CB").
 *
 * ATTENZIONE, limite di applicabilita'. Questi colori valgono per i grafici in
 * cui il colore NON porta identita': una serie sola, oppure due voci fisse di
 * una scomposizione (capitale/interessi). Nei grafici dove il colore distingue
 * fra piu' categorie va usata la palette categoriale validata CVD-safe in
 * `analytics/page.tsx`: la skill dataviz vieta sia di codificare l'identita'
 * con la luminosita' (quella codifica la quantita'), sia di assegnare il colore
 * in base al rango, perche' al variare della classifica i colori si
 * rimescolerebbero fra le categorie.
 *
 * Regola pratica: se le etichette stanno sull'asse (barre orizzontali), il
 * colore e' libero e si usano questi valori. Se l'identita' dipende dal colore
 * (legenda, torta, serie multiple sovrapposte), servono tinte distinte
 * validate, non questi due.
 */

/** Accento: la serie unica, o la parte in evidenza di una scomposizione. */
export const CHART_ACCENT = "#5FC4CB";

/** Neutro: il resto della scomposizione, griglie e assi. */
export const CHART_NEUTRAL = "#B0B5B9";

/** Sfondo delle superfici grafiche (Blu Profondo). */
export const CHART_GROUND = "#1C363D";

/** Testo primario sui grafici (Bianco Menta). */
export const CHART_INK = "#E9F1EA";

/** Griglia e assi: Platino attenuato, recessivo come chiede la skill dataviz. */
export const CHART_GRID = "rgba(176,181,185,0.18)";

/** Stile condiviso dei tooltip Recharts. */
export const TOOLTIP_STYLE = {
  background: CHART_GROUND,
  border: "1px solid rgba(176,181,185,0.25)",
  borderRadius: 8,
  color: CHART_INK,
  fontSize: 12,
} as const;

/** Stile dei tick degli assi. */
export const TICK_STYLE = { fontSize: 11, fill: CHART_NEUTRAL } as const;

/** Stile delle legende. */
export const LEGEND_STYLE = { color: CHART_NEUTRAL, fontSize: 12 } as const;
