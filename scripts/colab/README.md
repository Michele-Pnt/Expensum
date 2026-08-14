# Benchmark self-hosted su Colab

`gemma_selfhosted_benchmark.ipynb` testa `gemma2:2b` e `gemma3n:e2b` su GPU gratuita,
sui 4 task reali del bot (parsing testo, report settimanale/mensile, foto, audio).

Generato da `build_notebook.py` a partire dai prompt/dati REALI della codebase — non
scritto a mano — cosi' resta sincronizzato col codice di produzione. Se cambiano
`_SYSTEM_PROMPT`, `DEFAULT_CATEGORIES` o i template dei piani, rigenera con:

```
python scripts/colab/build_notebook.py
```

## Uso

1. Carica `gemma_selfhosted_benchmark.ipynb` su https://colab.research.google.com
2. `Runtime -> Change runtime type -> T4 GPU`
3. Accetta la licenza Gemma su Hugging Face (una volta sola, serve un account HF):
   - https://huggingface.co/google/gemma-3n-e2b-it
   - https://huggingface.co/google/gemma-2-2b-it
4. Esegui tutte le celle in ordine (`Runtime -> Run all`)
5. Alla fine scarica `gemma_colab_results.json` e passalo a Claude nella sessione
   locale: verrà punteggiato con le stesse funzioni usate per Mistral (stesso
   standard di misura, nessun confronto sbilanciato).

## Cosa NON fa questo notebook

- Non fa scoring — solo generazione. Lo scoring (confronto con ground truth, con le
  stesse metriche usate per Mistral) avviene in locale dopo il download del JSON.
- Non testa `gemma3n:e4b` (variante più pesante) di default — cambia `GEMMA3N_ID`
  nella cella dedicata se serve il tetto massimo di qualità oltre alla domanda
  "gira su un telefono di fascia bassa?".
