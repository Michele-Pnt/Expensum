# Log Daily - Setup e Schedulazione

## Panoramica

`log-daily` è un task automatico che analizza i file di log del progetto Finance-Agents e genera report giornalieri con:
- Errori critici da fixare subito
- Warning ricorrenti da monitorare
- Pattern anomali rilevati
- Trend rispetto ai report precedenti

## Output

Il task genera file di report in formato:
```
logs/log-report-YYYY-MM-DD.md
```

## Schedulazione

Per schedulare il task in modo che venga eseguito automaticamente ogni sera alle 22:00, eseguire il seguente comando tramite Claude:

```
Crea un scheduled task con questi parametri:
- taskId: log-daily
- description: Analizza i log degli ultimi 7 giorni e produce un report con errori critici e pattern anomali
- cronExpression: 0 22 * * *
- prompt: [vedi contenuto completo nel file SKILL.md]
```

### Comando completo per Claude

```
Crea un scheduled task chiamato "log-daily" che:
1. Si esegue ogni giorno alle 22:00 (cron: "0 22 * * *")
2. Analizza tutti i file .log in /sessions/optimistic-serene-mccarthy/mnt/Finance-Agents/logs/ modificati negli ultimi 7 giorni
3. Produce un report in logs/log-report-YYYY-MM-DD.md con errori, warning e pattern
```

### Nota tecnica

Il task non può essere creato automaticamente da un'altra sessione di scheduled task (per prevenire ricorsione). Deve essere creato manualmente dall'utente o da una sessione interattiva di Claude.

## Verifica schedulazione

Per verificare che il task sia stato schedulato correttamente:

```bash
# Controlla la lista dei task schedulati
claude list-scheduled-tasks

# Dovresti vedere:
# - taskId: log-daily
# - nextRunAt: [timestamp prossima esecuzione alle 22:00]
# - enabled: true
```

## Esecuzione manuale

Per eseguire il task manualmente senza aspettare le 22:00:

```bash
claude run-task log-daily
```

## Report generato

Il report include queste sezioni:
1. **Errori critici** - ERROR che richiedono azione immediata
2. **Warning ricorrenti** - Pattern di warning da monitorare
3. **Pattern anomali** - Comportamenti inusuali rilevati
4. **Trend** - Confronto con report precedenti
5. **Statistiche** - Metriche aggregate (totale errori, moduli problematici, orari critici)

## Esempio di utilizzo dei report

```bash
# Visualizza l'ultimo report generato
cat logs/log-report-$(date +%Y-%m-%d).md

# Confronta con il report di ieri
diff logs/log-report-$(date -d "yesterday" +%Y-%m-%d).md \
     logs/log-report-$(date +%Y-%m-%d).md

# Estrai solo gli errori critici dall'ultimo report
grep -A 50 "## 🔴 Errori critici" logs/log-report-$(date +%Y-%m-%d).md | head -50
```

## Personalizzazione

Per modificare il task (es. cambiare l'orario o i criteri di analisi):

1. Ferma il task schedulato:
   ```
   claude disable-task log-daily
   ```

2. Modifica i parametri desiderati

3. Ricrea il task con i nuovi parametri

4. Riattiva il task:
   ```
   claude enable-task log-daily
   ```

## Integrazione con il workflow

Il report giornaliero può essere integrato con:
- Notifiche Telegram per errori critici
- Dashboard Flask per visualizzazione grafica dei trend
- CI/CD pipeline per bloccare deploy se ci sono errori critici recenti
- Sistemi di alerting esterni (PagerDuty, Slack, etc.)

## Troubleshooting

### Il report non viene generato

1. Verifica che il task sia abilitato:
   ```bash
   claude list-scheduled-tasks | grep log-daily
   ```

2. Controlla i log del task stesso:
   ```bash
   cat ~/.claude/scheduled-tasks/log-daily/logs/latest.log
   ```

3. Verifica i permessi sulla cartella logs/:
   ```bash
   ls -la /sessions/optimistic-serene-mccarthy/mnt/Finance-Agents/logs/
   ```

### Nessun file .log trovato

Il task cerca file .log modificati negli ultimi 7 giorni. Se non ci sono log recenti:
- Verifica che il bot sia in esecuzione
- Controlla il path dei log in `main.py`
- Il report verrà comunque generato indicando l'assenza di log

### Report troppo grandi

Se i file di log sono molto grandi (>50MB), il task analizza solo le ultime 10,000 righe. Per modificare questo limite, aggiorna il parametro nel prompt del task.

## Manutenzione

### Pulizia report vecchi

I report si accumulano nel tempo. Per archiviarli:

```bash
# Sposta report più vecchi di 30 giorni in archivio
find logs/ -name "log-report-*.md" -mtime +30 -exec mv {} logs/archive/ \;

# Comprimi archivio
tar -czf logs/archive/reports-$(date +%Y-%m).tar.gz logs/archive/log-report-*.md
rm logs/archive/log-report-*.md
```

### Aggiornamento del task

Se viene modificata la logica di analisi, aggiorna il task:

```bash
# Disabilita task attuale
claude disable-task log-daily

# Ricrea con nuovo prompt
# [seguire le istruzioni di schedulazione sopra]
```
