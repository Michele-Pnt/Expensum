# Token Usage Samples

I sample di questo folder servono al runner `scripts/measure_token_usage.py`.

- `text/`: input testuali grezzi per il parser LLM
- `audio/`: descriptor JSON con il transcript già estratto, usato per simulare il flusso voce
- `photo/`: descriptor JSON con il testo OCR già estratto, usato per simulare il flusso scontrino

I file audio/foto reali non sono necessari per la misura dei token: il runner misura il consumo LLM nei punti decisionali del flusso.
