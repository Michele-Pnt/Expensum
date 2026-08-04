# Notifiche utenti in sospeso

Elenco delle feature user-facing implementate **dall'ultima comunicazione broadcast
mandata agli utenti**, da consolidare in un'unica email quando lo sviluppo prodotto
rallenta. Non è un changelog tecnico: contiene solo ciò che un utente noterebbe o
di cui gli importerebbe, con un accenno a *perché* dovrebbe interessargli.

**Regola d'uso**: quando si invia una notifica broadcast (nuovo script in
`scripts/notify_*.py`), spostare le voci coperte in fondo al file sotto "Già
comunicate" con la data di invio, così il file resta sempre "quello che manca".

---

## Ultima comunicazione inviata

**Trasferimenti conto-conto + referral** — `scripts/notify_transfers_and_referral.py`
(commit `b987a90`).

---

## Da comunicare (accumulate da allora)

### Già in `main`, mai annunciate

- **Obiettivi di risparmio** (commit `53892e8`, tour guidato `802b701`) — 5 tipi di
  obiettivo, avanzamento e voto mensile automatico, riepilogo nel report mensile.
  *(già oggetto di uno script di annuncio pronto ma non ancora inviato, vedi sotto)*
- **Streak giornaliera** (commit `5bbfc16`) — 2 transazioni/giorno per cicli
  crescenti (14→28→42gg), reward di 14 giorni di Pro a ogni ciclo completato.
- **Categorizzazione adattiva** (commit `025a32e`, fix `0e057ad`) — pattern di spesa
  ricorrenti proposti come categoria dopo 5 occorrenze in 90 giorni.
- **Report Free sfocati dal secondo mese + CTA upgrade** (commit `5c1009e`,
  `d1765a6`, `4b74c41`) — cambia cosa vede un utente Free nei report dal secondo mese
  in poi: va comunicato con attenzione, è una restrizione percepita, non un regalo.

### In questo branch, non ancora deployate (sessione corrente)

- **Motore di gamification**: achievement, XP, livelli. 48 traguardi in 7 famiglie
  (costanza, ritmo mensile ciclico, canali, classificazione, report, obiettivi,
  streak, primi passi) più i cicli mensili perpetui. Disponibile anche al piano
  Free (una sola famiglia è Pro-only: gli obiettivi di risparmio).
- **Referral: nuove regole** — 14 giorni di Pro per ogni invito andato a buon fine
  (sia per chi invita sia per l'invitato), fino a 3 inviti premiati per chi invita
  (42gg massimo); il link **non scade mai**: dal 4° invito in poi chi invita non
  guadagna più nulla ma chi viene invitato continua a ricevere i suoi 14 giorni.
- **Budget suggerito riprogettato** — non più la media delle spese passate, ma un
  piano costruito dal reddito: quanto resta da distribuire dopo risparmio target e
  spese fisse, ripartito per categoria in proporzione allo storico.
- **Archiviazione categorie** — una categoria non più usata si può archiviare invece
  di doverla cancellare (che oggi falliva se aveva spese collegate): lo storico
  resta intatto, sparisce solo dalle scelte future.
- **Fix capitale nell'analisi patrimoniale** — il grafico "Andamento capitale"
  mostrava un totale negativo per chi registra spese senza indicare il conto; ora è
  coerente con "Il mio spazio". Nessuna azione utente, ma vale la pena menzionarlo
  se qualcuno l'aveva notato e segnalato.

## Script di annuncio già pronti, in attesa di invio

- `scripts/notify_savings_goals.py` — annuncio obiettivi di risparmio (Pro,
  Postgres). Pronto, mai eseguito nemmeno in dry-run su produzione.
- Nessuno script di annuncio scritto ancora per gamification, nuove regole
  referral, budget planner o archiviazione categorie: da scrivere quando si decide
  di comunicare, probabilmente in un unico invio combinato vista la vicinanza
  temporale delle feature.

---

## Già comunicate

*(vuoto — nessun invio da quando questo file esiste)*
