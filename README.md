# Financial Analyzer & Predictor Agent 💰🤖

An autonomous Python agent that connects to your Notion expense workspace, performs monthly statistical analysis, forecasts next month's spending, leverages AI (Google Gemini 2.5 Flash) for advanced insights, generates visual charts, and delivers a structured report directly to Telegram.

---

## Key Features

- **Multi-Database Notion Integration**: Connects to up to 7 Notion databases (Expenses, Categories, Monthly Balance, Income, Accounts, Subscriptions, Pay/Transfer) to reconstruct a complete picture of your finances.
- **Statistical Analysis & Trends**: Computes total expenses, income, daily averages, 3–6 month moving averages, and detects spending anomalies against historical data.
- **Next-Month Forecasting**: Identifies recurring fixed expenses, calculates weighted averages for variable costs, and applies monthly seasonality coefficients to produce optimistic / base / pessimistic projections.
- **AI-Powered Insights**: Uses Gemini 2.5 Flash with a Chain-of-Thought prompt to generate a reasoned, hallucination-resistant analysis grounded in real data.
- **Chart Generation**: Produces dark-themed pie, bar, and line charts (matplotlib + seaborn) sent alongside the text report.
- **Telegram Reporting**: Sends a Markdown-formatted message with automatic chunking for Telegram's 4 096-character limit, plus chart images.
- **Automatic Scheduling**: Runs the analysis on the 1st of every month via APScheduler, with optional systemd user service for Linux servers / Raspberry Pi.

---

## 🛠️ System Requirements

- Python 3.10+
- A Notion workspace containing at least:
  - An **Expenses** database (with `Amount`, `Date`, `Name`, and a relation to a `Categories` database)
  - A **Categories** database (used as a lookup table; optionally includes an `Average` field)
  - A **Monthly Balance** database (with a computed `Net Savings` formula field)
  - An **Income** database (with `Amount`, `Date`, `Name`)
  - An **Accounts** database (with balance-related rollup/formula fields)
- A Telegram bot (created via [@BotFather](https://t.me/botfather))
- A Google AI Studio API key (Gemini)

---

## 🚀 Setup & Installation

### 1. Clone the project and prepare the environment
```bash
git clone <your-repo-url>
cd Finance-Agents

# Create and activate a virtual environment
python -m venv .venv
source .venv/bin/activate  # on Windows: .venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt
```

### 2. Configure environment variables
Copy the template configuration file:
```bash
cp .env.example .env
```
Open `.env` in your favorite editor and fill in:
- **`NOTION_API_KEY`**: Create an internal integration at [Notion Developers](https://www.notion.so/my-integrations).
- **Database IDs**: Open each database in the browser, copy the ID from the URL, and paste it into the corresponding field (`NOTION_EXPENSE_DATABASE_ID`, `NOTION_CATEGORIES_DATABASE_ID`, `NOTION_MONTHLY_BALANCE_DATABASE_ID`, `NOTION_INCOME_DATABASE_ID`, `NOTION_ACCOUNTS_DATABASE_ID`).
- **`GEMINI_API_KEY`**: Get a free key from [Google AI Studio](https://aistudio.google.com/app/apikey).
- **Telegram Auth**: Enter your bot token and your personal Chat ID.

> **IMPORTANT: Notion Database Connections**
> For each Notion database you want the agent to access, click the three dots `...` in the top-right corner, select **Connections**, and add the integration you created.

### 3. Customize column names
If your Notion columns have different names, update them in `.env`:
```env
NOTION_COL_DATE=Date
NOTION_COL_CATEGORY=Categories
NOTION_COL_NAME=Name
NOTION_COL_AMOUNT=Amount
NOTION_MB_DATE=Month
NOTION_MB_NET_SAVINGS=Net Savings
```

---

## 🏃‍♂️ Usage

### Manual Execution
Run the agent to analyze the previous month:
```bash
python main.py
```

Analyze a **specific month** (e.g., January 2026):
```bash
python main.py --month 2026-01
```

Test formatting and local statistics **without calling Gemini or sending Telegram messages** (uses mock data instead of Notion):
```bash
python main.py --dry-run
```

Fetch **real data from Notion** but skip the Gemini API call and Telegram delivery — useful for debugging data extraction:
```bash
python main.py --debug-data
```

### Scheduled Execution (Monthly)
Leave the bot running on a server or Raspberry Pi to automatically send the report on the 1st of every month at the configured time:
```bash
python scheduler.py
```
*(Alternatively, call `python main.py` via a system cron job: `0 8 1 * * /path/to/.venv/bin/python /path/to/main.py`)*

### Background Daemon with systemd (recommended on Linux)
The repository includes scripts to install a **systemd user service** that keeps `scheduler.py` running in the background.

1. Set the schedule in `.env`:
```env
SCHEDULE_HOUR=8
SCHEDULE_MINUTE=0
```

2. Install the service:
```bash
bash scripts/install_systemd_user_service.sh
```

3. Verify it started:
```bash
systemctl --user status agente-analizzatore-spese.service
```

4. Follow logs in real time:
```bash
journalctl --user -u agente-analizzatore-spese.service -f
```

To keep it running after logout, enable user lingering:
```bash
sudo loginctl enable-linger $USER
```

To uninstall:
```bash
bash scripts/uninstall_systemd_user_service.sh
```

---

## 🏛️ Architecture

```
Finance-Agents/
├── main.py                  # Orchestrator — runs the full 7-step pipeline
├── config.py                # Loads & validates .env configuration
├── scheduler.py             # APScheduler-based monthly cron daemon
├── src/
│   ├── notion_client.py     # Notion API client (pagination, retry, multi-DB)
│   ├── data_processor.py    # Pandas-based aggregation, trends & anomalies
│   ├── forecaster.py        # Statistical forecaster (fixed/variable split + seasonality)
│   ├── gemini_client.py     # Gemini 2.5 Flash client (Chain-of-Thought prompt)
│   ├── chart_generator.py   # Matplotlib/Seaborn chart generation (pie, bar, line)
│   ├── report_builder.py    # Fallback Markdown report builder (no-AI mode)
│   └── telegram_client.py   # Telegram Bot API client (send text + photos, auto-split)
├── scripts/
│   ├── install_systemd_user_service.sh
│   ├── run_scheduler.sh
│   └── uninstall_systemd_user_service.sh
├── tests/
│   ├── test_data_processor.py
│   └── test_forecaster.py
├── requirements.txt
└── .env.example
```

### Pipeline Overview

| Step | Module | Description |
|------|--------|-------------|
| 1 | `notion_client.py` | Fetches expenses, categories, monthly balances, income, and account data from Notion with automatic pagination and exponential-backoff retry. |
| 2 | `data_processor.py` | Aggregates transactions by month and category using pandas; computes trends, daily averages, and delta vs. historical mean. |
| 3 | `forecaster.py` | Splits expenses into fixed (recurring ±8% tolerance) and variable; applies weighted average + seasonality to produce a forecast range. |
| 4 | `chart_generator.py` | Generates dark-themed pie, grouped bar, and historical line charts saved as temporary PNGs. |
| 5 | `gemini_client.py` | Sends structured data + forecast to Gemini 2.5 Flash with a Chain-of-Thought prompt; strips the reasoning section from the response. |
| 6 | `report_builder.py` | Builds a purely statistical fallback report when Gemini is unavailable or in dry-run mode. |
| 7 | `telegram_client.py` | Sends chart images first, then the Markdown report (auto-split if > 4 096 chars) to the configured Telegram chat. |

All network operations (Notion, Gemini, Telegram) use `tenacity` for automatic retry with exponential backoff on transient errors (HTTP 429, 500, 503).

---

## 📦 Dependencies

| Package | Purpose |
|---------|---------|
| `notion-client` | Official Notion SDK (API 2025-09-03) |
| `google-genai` | Google Generative AI SDK (Gemini) |
| `python-telegram-bot` | Telegram Bot API wrapper |
| `APScheduler` | Cron-like job scheduling |
| `pandas` | Data aggregation and manipulation |
| `matplotlib` + `seaborn` | Chart generation |
| `tenacity` | Retry logic with exponential backoff |
| `python-dotenv` | `.env` file loading |

---

## 🧪 Testing

Run the test suite:
```bash
pytest tests/ -v
```

Available test modules:
- `test_data_processor.py` — Tests for aggregation, trend detection, and income processing.
- `test_forecaster.py` — Tests for fixed/variable expense identification and forecast calculations.

---

## 📝 License

This project is provided as-is for personal use.
