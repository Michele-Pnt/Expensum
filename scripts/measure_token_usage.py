#!/usr/bin/env python3
"""Misura token usage per i principali flussi LLM dell'agente.

Il runner esegue un batch controllato su 5 utenti simulati e raccoglie:
- eventi nel ledger `llm_usage_events`
- un CSV per-request in `reports/token_usage_<ts>.csv`
- un report Markdown con mediane, p90 e costi stimati
- grafici PNG per confronto per scenario

Modalità:
- `--dry-run`: nessuna chiamata esterna, usage sintetica ma ledger popolato
- live: usa i client reali per text/audio/photo e report weekly/monthly
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
import os
import random
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path
from statistics import median
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import matplotlib.pyplot as plt
import pandas as pd
import seaborn as sns

from config import Config
from src.expense_parser import ExpenseParser
from src.gemini_client import GeminiClient
from src.llm_usage_tracker import (
    build_request_key,
    estimate_reserved_tokens,
    normalize_usage_metadata,
)
from src.mistral_client import MistralClient
from src.user_store import UserStore

logger = logging.getLogger("financial_agent.measure_token_usage")
OPERATIONS = ("text", "audio", "photo", "weekly", "monthly")

# Mappa (scenario, suboperation) → nome operazione canonico usato dal bot
_CANONICAL_OPERATION: dict[tuple[str, str], str] = {
    ("text", "expense_parse"): "expense_parse",
    ("audio", "expense_parse"): "expense_parse",
    ("photo", "expense_parse"): "expense_parse",
    ("weekly", "report_generate"): "weekly_plan",
    ("monthly", "report_generate"): "monthly_report",
}
SIMULATED_USERS = 5
REQUESTS_PER_OPERATION = 10
SYSTEM_CHAT_ID = "system"


@dataclass(slots=True)
class MeasurementRow:
    """Riga normalizzata del CSV di misura."""

    timestamp: str
    scenario: str
    suboperation: str
    chat_id: str
    request_key: str
    provider: str
    model: str
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    estimated_cost_amount: float
    estimated_cost_currency: str
    dry_run: bool
    status: str
    sample_name: str
    source_path: str


@dataclass(slots=True)
class OperationSample:
    """Fixture di input usata dal runner."""

    name: str
    text: str
    source_path: str


@dataclass(slots=True)
class ReportSample:
    """Contesto sintetico per i report settimanali/mensili."""

    data_text: str
    accounts_text: str
    forecast_text: str
    current_month_label: str
    next_month_label: str
    total_income: str
    total_amount: str
    total_accounts_balance: str
    net_savings: str


class MeasurementRunner:
    """Esegue il batch di misura, scrive il ledger e genera i report."""

    def __init__(
        self,
        samples_dir: Path,
        out_dir: Path,
        dry_run: bool,
        db_url: str,
        workers: int,
        users: int,
        requests_per_operation: int,
    ) -> None:
        self.samples_dir = samples_dir
        self.out_dir = out_dir
        self.dry_run = dry_run
        self.db_url = db_url
        self.workers = max(1, workers)
        self.users = max(1, users)
        self.requests_per_operation = max(1, requests_per_operation)
        self.timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.csv_path = self.out_dir / f"token_usage_{self.timestamp}.csv"
        self.summary_path = self.out_dir / f"token_usage_summary_{self.timestamp}.md"
        self.out_dir.mkdir(parents=True, exist_ok=True)
        self.store = UserStore(db_url=self.db_url)
        self.store.add_user(SYSTEM_CHAT_ID)
        self.users_ids = [f"measure-user-{idx}" for idx in range(1, self.users + 1)]
        for chat_id in self.users_ids:
            self.store.add_user(chat_id)
        self.rows: list[MeasurementRow] = []
        self._report_templates = self._build_report_templates()

    def run(self) -> None:
        """Esegue tutte le operazioni e salva i report finali."""
        self.out_dir.mkdir(parents=True, exist_ok=True)
        samples = self._load_samples()
        tasks = self._build_tasks(samples)

        logger.info(
            "Avvio misura token: dry_run=%s, users=%s, requests_per_operation=%s, workers=%s",
            self.dry_run,
            self.users,
            self.requests_per_operation,
            self.workers,
        )

        if self.workers == 1:
            for task in tasks:
                self.rows.extend(self._run_task(task, samples))
        else:
            with ThreadPoolExecutor(max_workers=self.workers) as executor:
                futures = [executor.submit(self._run_task, task, samples) for task in tasks]
                for future in as_completed(futures):
                    self.rows.extend(future.result())

        self._write_csv()
        self._write_summary()
        self._write_charts()

    def _build_tasks(self, samples: dict[str, list[OperationSample]]) -> list[tuple[str, str, int, OperationSample]]:
        tasks: list[tuple[str, str, int, OperationSample]] = []
        for scenario in OPERATIONS:
            scenario_samples = samples[scenario]
            for request_index in range(self.requests_per_operation):
                for user_index, chat_id in enumerate(self.users_ids):
                    sample = scenario_samples[(request_index + user_index) % len(scenario_samples)]
                    tasks.append((scenario, chat_id, request_index, sample))
        return tasks

    def _run_task(
        self,
        task: tuple[str, str, int, OperationSample],
        samples: dict[str, list[OperationSample]],
    ) -> list[MeasurementRow]:
        scenario, chat_id, request_index, sample = task
        if scenario == "text":
            return self._measure_expense_parse(chat_id, request_index, sample, scenario)
        if scenario == "audio":
            return self._measure_expense_parse(chat_id, request_index, sample, scenario)
        if scenario == "photo":
            return self._measure_expense_parse(chat_id, request_index, sample, scenario)
        if scenario == "weekly":
            return self._measure_report(chat_id, request_index, sample, scenario, provider="gemini")
        if scenario == "monthly":
            return self._measure_report(chat_id, request_index, sample, scenario, provider="mistral")
        raise ValueError(f"Scenario non supportato: {scenario}")

    def _measure_expense_parse(
        self,
        chat_id: str,
        request_index: int,
        sample: OperationSample,
        scenario: str,
    ) -> list[MeasurementRow]:
        request_key = build_request_key("measure", scenario, chat_id, request_index, sample.name, sample.text)
        provider = "mistral"
        model = Config.MISTRAL_SMALL_MODEL
        reservation_created = False
        try:
            self.store.reserve_llm_tokens(
                chat_id=chat_id,
                request_key=request_key,
                operation="expense_parse",
                provider=provider,
                model=model,
                reserved_tokens=estimate_reserved_tokens("expense_parse"),
            )
            reservation_created = True
        except Exception as exc:
            logger.warning("[%s] Reservation fallita: %s", chat_id, exc)

        if self.dry_run:
            usage = self._synthetic_usage(sample.text, provider, model, scale=1.0)
            result = {"usage_metadata": usage}
        else:
            parser = ExpenseParser(categories=["Cibo", "Trasporti", "Casa", "Salute", "Abbonamenti"])
            result, usage = parser.parse_with_usage(sample.text)
            usage = normalize_usage_metadata(usage)
            if result is None and not usage:
                usage = {}

        return self._finalize_rows(
            chat_id=chat_id,
            request_key=request_key,
            scenario=scenario,
            suboperation="expense_parse",
            sample=sample,
            provider=provider,
            model=model,
            usage=result.get("usage_metadata", {}) if isinstance(result, dict) else usage,
            reservation_created=reservation_created,
        )

    def _measure_report(
        self,
        chat_id: str,
        request_index: int,
        sample: OperationSample,
        scenario: str,
        provider: str,
    ) -> list[MeasurementRow]:
        request_key = build_request_key("measure", scenario, chat_id, request_index, sample.name, sample.text)
        if provider == "gemini":
            model = Config.GEMINI_MODEL
        else:
            model = Config.MISTRAL_SMALL_MODEL

        reservation_created = False
        try:
            canonical_op = _CANONICAL_OPERATION.get((scenario, "report_generate"), f"{scenario}_report")
            self.store.reserve_llm_tokens(
                chat_id=chat_id,
                request_key=request_key,
                operation=canonical_op,
                provider=provider,
                model=model,
                reserved_tokens=estimate_reserved_tokens(canonical_op),
            )
            reservation_created = True
        except Exception as exc:
            logger.warning("[%s] Reservation report fallita: %s", chat_id, exc)

        if self.dry_run:
            usage = self._synthetic_usage(sample.text, provider, model, scale=2.0)
            result_text = f"# {scenario.title()} report sintetico"
        else:
            if provider == "gemini":
                client = GeminiClient()
                result_text, usage = client.analyze_and_generate_report(
                    data_text=sample.text,
                    accounts_text=self._report_templates.accounts_text,
                    forecast_text=self._report_templates.forecast_text,
                    current_month_label=self._report_templates.current_month_label,
                    next_month_label=self._report_templates.next_month_label,
                    total_income=self._report_templates.total_income,
                    total_amount=self._report_templates.total_amount,
                    total_accounts_balance=self._report_templates.total_accounts_balance,
                    net_savings=self._report_templates.net_savings,
                )
            else:
                client = MistralClient()
                result_text, usage = client.analyze_and_generate_report(
                    data_text=sample.text,
                    accounts_text=self._report_templates.accounts_text,
                    forecast_text=self._report_templates.forecast_text,
                    current_month_label=self._report_templates.current_month_label,
                    next_month_label=self._report_templates.next_month_label,
                    total_income=self._report_templates.total_income,
                    total_amount=self._report_templates.total_amount,
                    total_accounts_balance=self._report_templates.total_accounts_balance,
                    net_savings=self._report_templates.net_savings,
                )
            usage = normalize_usage_metadata(usage)
            _ = result_text

        return self._finalize_rows(
            chat_id=chat_id,
            request_key=request_key,
            scenario=scenario,
            suboperation="report_generate",
            sample=sample,
            provider=provider,
            model=model,
            usage=usage,
            reservation_created=reservation_created,
        )

    def _finalize_rows(
        self,
        chat_id: str,
        request_key: str,
        scenario: str,
        suboperation: str,
        sample: OperationSample,
        provider: str,
        model: str,
        usage: dict[str, Any],
        reservation_created: bool,
    ) -> list[MeasurementRow]:
        normalized_usage = normalize_usage_metadata(usage)
        rows: list[MeasurementRow] = []

        if usage:
            try:
                event = self.store.finalize_llm_usage(
                    chat_id=chat_id,
                    request_key=request_key,
                    prompt_tokens=normalized_usage.get("prompt_tokens", 0),
                    completion_tokens=normalized_usage.get("completion_tokens", 0),
                    total_tokens=normalized_usage.get("total_tokens", 0),
                    provider=normalized_usage.get("provider", provider),
                    model=normalized_usage.get("model", model),
                    operation=_CANONICAL_OPERATION.get((scenario, suboperation), f"{scenario}_{suboperation}"),
                    thinking_tokens=normalized_usage.get("thinking_tokens"),
                    cached_tokens=normalized_usage.get("cached_tokens"),
                )
                estimated_cost = float(event.estimated_cost_amount or 0.0)
                currency = event.estimated_cost_currency or "USD"
            except Exception as exc:
                logger.warning("[%s] finalize_llm_usage fallita: %s", chat_id, exc)
                estimated_cost = 0.0
                currency = "USD"
        else:
            if reservation_created:
                try:
                    self.store.release_llm_reservation(chat_id, request_key, reason="no_usage_metadata")
                except Exception:
                    pass
            estimated_cost = 0.0
            currency = "USD"

        rows.append(
            MeasurementRow(
                timestamp=datetime.now().isoformat(),
                scenario=scenario,
                suboperation=suboperation,
                chat_id=chat_id,
                request_key=request_key,
                provider=provider,
                model=model,
                prompt_tokens=normalized_usage.get("prompt_tokens", 0),
                completion_tokens=normalized_usage.get("completion_tokens", 0),
                total_tokens=normalized_usage.get("total_tokens", 0),
                estimated_cost_amount=estimated_cost,
                estimated_cost_currency=currency,
                dry_run=self.dry_run,
                status="finalized" if usage else "released",
                sample_name=sample.name,
                source_path=sample.source_path,
            )
        )
        return rows

    def _synthetic_usage(self, prompt_text: str, provider: str, model: str, scale: float) -> dict[str, Any]:
        prompt_tokens = max(20, int(len(prompt_text) / 4))
        completion_tokens = max(12, int(prompt_tokens * 0.35 * scale))
        total_tokens = prompt_tokens + completion_tokens
        usage = {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": total_tokens,
            "provider": provider,
            "model": model,
        }
        return usage

    def _build_report_templates(self) -> ReportSample:
        data_text = (
            "Spesa totale mese: 1240.50 EUR\n"
            "Categorie top: Supermercato 320.40, Trasporti 124.30, Ristoranti 98.00\n"
            "Storico: spesa media 1160.20 EUR, variazione mese su mese +6.9%\n"
            "Anomalie: una spesa abbonamento duplicata da verificare\n"
        )
        accounts_text = (
            "Conti correnti attuali:\n"
            "- Main Bank: 1850.00 EUR\n"
            "- Savings: 4120.00 EUR\n"
            "Totale saldi conti: 5970.00 EUR\n"
        )
        forecast_text = (
            "Previsione mese prossimo:\n"
            "- ottimistica 1080.00 EUR\n"
            "- base 1210.00 EUR\n"
            "- pessimistica 1380.00 EUR\n"
        )
        return ReportSample(
            data_text=data_text,
            accounts_text=accounts_text,
            forecast_text=forecast_text,
            current_month_label="Aprile 2026",
            next_month_label="Maggio 2026",
            total_income="2900.00",
            total_amount="1240.50",
            total_accounts_balance="5970.00",
            net_savings="1659.50",
        )

    def _load_samples(self) -> dict[str, list[OperationSample]]:
        """Carica i sample dalla directory configurata."""
        samples: dict[str, list[OperationSample]] = {}
        samples["text"] = self._load_text_samples(self.samples_dir / "text")
        samples["audio"] = self._load_descriptor_samples(self.samples_dir / "audio", text_key="transcript")
        samples["photo"] = self._load_descriptor_samples(self.samples_dir / "photo", text_key="ocr_text")
        samples["weekly"] = self._build_report_input_samples("weekly")
        samples["monthly"] = self._build_report_input_samples("monthly")
        return samples

    def _load_text_samples(self, folder: Path) -> list[OperationSample]:
        samples: list[OperationSample] = []
        for path in sorted(folder.glob("*.txt")):
            samples.append(OperationSample(name=path.stem, text=path.read_text(encoding="utf-8").strip(), source_path=str(path)))
        if not samples:
            raise FileNotFoundError(f"Nessun sample testo trovato in {folder}")
        return samples

    def _load_descriptor_samples(self, folder: Path, text_key: str) -> list[OperationSample]:
        samples: list[OperationSample] = []
        for path in sorted(folder.glob("*.json")):
            payload = json.loads(path.read_text(encoding="utf-8"))
            text = str(payload.get(text_key, "")).strip()
            samples.append(OperationSample(name=payload.get("name", path.stem), text=text, source_path=str(path)))
        if not samples:
            raise FileNotFoundError(f"Nessun sample descriptor trovato in {folder}")
        return samples

    def _build_report_input_samples(self, scenario: str) -> list[OperationSample]:
        report = self._report_templates
        text = report.data_text if scenario == "weekly" else f"{report.data_text}\n{report.accounts_text}\n{report.forecast_text}"
        return [
            OperationSample(name=f"{scenario}_sample_{idx}", text=text, source_path=f"generated:{scenario}")
            for idx in range(1, 4)
        ]

    def _write_csv(self) -> None:
        with self.csv_path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(asdict(self.rows[0]).keys()))
            writer.writeheader()
            for row in self.rows:
                writer.writerow(asdict(row))
        logger.info("CSV scritto in %s", self.csv_path)

    def _write_summary(self) -> None:
        df = pd.DataFrame([asdict(row) for row in self.rows])
        grouped = df.groupby(["scenario", "suboperation"], dropna=False)

        lines = [
            f"# Token Usage Summary {self.timestamp}",
            "",
            f"- Dry run: {self.dry_run}",
            f"- Users: {self.users}",
            f"- Requests per operation: {self.requests_per_operation}",
            f"- Rows: {len(df)}", 
            "",
            "| Scenario | N | Median tokens | P90 tokens | Total tokens | Estimated cost |",
            "| --- | ---: | ---: | ---: | ---: | ---: |",
        ]

        for (scenario, suboperation), group in grouped:
            tokens = group["total_tokens"].tolist()
            cost = float(group["estimated_cost_amount"].sum())
            p90 = self._percentile(tokens, 0.9)
            lines.append(
                f"| {scenario}/{suboperation} | {len(group)} | {median(tokens):.1f} | {p90:.1f} | {sum(tokens)} | {cost:.6f} |"
            )

        lines.extend([
            "",
            "## Notes",
            "- I record con `status=finalized` sono quelli con usage reale o sintetica.",
            "- I record `released` indicano che la reservation non ha ricevuto usage.",
            "",
        ])

        self.summary_path.write_text("\n".join(lines), encoding="utf-8")
        logger.info("Summary scritto in %s", self.summary_path)

    def _write_charts(self) -> None:
        df = pd.DataFrame([asdict(row) for row in self.rows])
        sns.set_theme(style="whitegrid")
        chart_data = df.groupby("scenario")["total_tokens"].agg(["median", "mean", "max"]).reset_index()

        plt.figure(figsize=(10, 6))
        sns.barplot(
            data=chart_data,
            x="scenario",
            y="median",
            hue="scenario",
            palette="viridis",
            dodge=False,
            legend=False,
        )
        plt.title("Median token usage per scenario")
        plt.ylabel("Median tokens")
        plt.xlabel("")
        plt.tight_layout()
        median_chart = self.out_dir / f"token_usage_median_{self.timestamp}.png"
        plt.savefig(median_chart, dpi=150)
        plt.close()

        plt.figure(figsize=(10, 6))
        sns.boxplot(
            data=df,
            x="scenario",
            y="total_tokens",
            hue="scenario",
            palette="pastel",
            dodge=False,
            legend=False,
        )
        plt.title("Token distribution per scenario")
        plt.ylabel("Total tokens")
        plt.xlabel("")
        plt.tight_layout()
        box_chart = self.out_dir / f"token_usage_boxplot_{self.timestamp}.png"
        plt.savefig(box_chart, dpi=150)
        plt.close()

        logger.info("Grafici scritti in %s e %s", median_chart, box_chart)

    @staticmethod
    def _percentile(values: list[int], percentile: float) -> float:
        if not values:
            return 0.0
        ordered = sorted(values)
        index = int(round((len(ordered) - 1) * percentile))
        return float(ordered[index])


def _configure_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Misura token usage per i flussi LLM")
    parser.add_argument("--dry-run", action="store_true", help="Usa usage sintetica senza chiamare API esterne")
    parser.add_argument("--workers", type=int, default=1, help="Numero di worker concorrenti")
    parser.add_argument("--samples-dir", type=Path, default=Path(__file__).parent / "samples", help="Directory dei sample")
    parser.add_argument("--out", type=Path, default=Path("reports"), help="Directory di output")
    parser.add_argument("--db-url", type=str, default=None, help="Database URL per il ledger")
    parser.add_argument("--users", type=int, default=SIMULATED_USERS, help="Numero di utenti simulati")
    parser.add_argument("--requests-per-operation", type=int, default=REQUESTS_PER_OPERATION, help="Numero di richieste per operazione")
    return parser.parse_args()


def main() -> int:
    _configure_logging()
    args = _parse_args()
    if not args.dry_run and os.getenv("RUN_TOKEN_MEASURE") != "1":
        print("RUN_TOKEN_MEASURE=1 is required for live runs")
        return 1
    db_url = args.db_url or (
        f"sqlite:///{args.out / 'token_usage_measure.db'}" if args.dry_run else Config.DATABASE_URL
    )

    runner = MeasurementRunner(
        samples_dir=args.samples_dir,
        out_dir=args.out,
        dry_run=args.dry_run,
        db_url=db_url,
        workers=args.workers,
        users=args.users,
        requests_per_operation=args.requests_per_operation,
    )
    runner.run()
    print(f"CSV: {runner.csv_path}")
    print(f"Summary: {runner.summary_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
