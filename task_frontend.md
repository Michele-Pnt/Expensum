# Task List: Implementazione MUI e Ristrutturazione Frontend

- [/] **Fase 1: Setup e Configurazione MUI**
  - [/] Installare le dipendenze MUI (`@mui/material`, `@emotion/react`, `@emotion/styled`, `@mui/icons-material`) nel `frontend`.
  - [ ] Creare il file `src/theme/theme.ts` configurando i colori richiesti (Verde acqua, Verde, Azzurro).
  - [ ] Modificare `src/app/layout.tsx` per includere `ThemeProvider`, `AppRouterCacheProvider` (o simile per Next.js) e `CssBaseline`.
- [ ] **Fase 2: Struttura Base e Componenti Comuni**
  - [ ] Creare i componenti strutturali (es. Navbar/Header minimale).
  - [ ] Adattare il layout per mantenere le pagine separate senza Sidebar forzata.
- [x] **Fase 3: Refactoring delle Pagine Esistenti**
  - [x] Riscrivere `src/app/page.tsx` (Landing Page) implementando la struttura derivata dall'analisi competitor (Hero, Features).
  - [x] Refactoring di `src/app/analytics/page.tsx` usando MUI.
  - [x] Refactoring di `src/app/abbonamenti/page.tsx` usando MUI.
- [x] **Fase 4: Integrazione Mini App**
  - [x] Creare/Adattare l'interfaccia dedicata per Telegram (Mini App) ottimizzata per Mobile.
- [x] **Fase 5: Verifica**
  - [x] Testare l'interfaccia visivamente.
  - [x] Assicurarsi che i vecchi stili non causino conflitti bloccanti durante il transitorio.
