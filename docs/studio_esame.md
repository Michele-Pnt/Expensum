# Documentazione tecnica per l'esame — Expensum

Questo documento descrive in dettaglio il codice che gestisce due funzionalità chiave dell'applicazione:

1. **"Il mio spazio"** — pagina di gestione CRUD per conti, categorie, spese, entrate e abbonamenti
2. **Inserimento transazioni via chat** — parsing AI di un messaggio testuale/vocale/foto e salvataggio su DB
3. **Analytics** — cruscotto statistico con grafici e aggregazioni sui dati finanziari

---

## Architettura generale

```
Browser (Next.js)
    │
    │  HTTP  /api/*
    ▼
Next.js proxy (next.config.ts)   ← riscrive tutte le chiamate /api/* verso localhost:5000
    │
    ▼
Flask (src/dashboard/app.py)     ← gestisce le route REST
    │
    ▼
PostgresStorage (src/storage/postgres_storage.py)   ← esegue le query sul DB
    │
    ▼
PostgreSQL
```

Il frontend **non** parla direttamente col database: ogni operazione passa per le API Flask.

---

## Schema logico del database (tabelle coinvolte)

```
users
├── chat_id (PK, String)
└── ...

accounts
├── id (PK, Integer)
├── user_id (FK → users.chat_id)
├── name (String)
├── opening_balance (Numeric 12,2)
├── currency (String, default "EUR")
└── account_type (String, nullable)

user_categories
├── id (PK, Integer)
├── user_id (FK → users.chat_id)
├── name (String)
└── monthly_budget (Numeric 12,2, nullable)

expenses
├── id (PK, Integer, autoincrement)
├── user_id (FK → users.chat_id)
├── expense_date (Date)
├── amount (Numeric 12,2)
├── name (String)
├── category_id (FK → user_categories.id, nullable)
└── account_id (FK → accounts.id, nullable)

incomes
├── id (PK, Integer, autoincrement)
├── user_id (FK → users.chat_id)
├── income_date (Date)
├── amount (Numeric 12,2)
├── name (String)
├── income_type (String, nullable)
└── account_id (FK → accounts.id)
```

---

## Modelli SQLAlchemy — `src/storage/models.py`

```python
class Expense(Base):
    __tablename__ = "expenses"
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(String, ForeignKey("users.chat_id"), nullable=False)
    expense_date = Column(Date, nullable=False)
    amount = Column(Numeric(12, 2), nullable=False)
    name = Column(String, nullable=False)
    category_id = Column(Integer, ForeignKey("user_categories.id"), nullable=True)
    account_id = Column(Integer, ForeignKey("accounts.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

class Account(Base):
    __tablename__ = "accounts"
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(String, ForeignKey("users.chat_id"), nullable=False)
    name = Column(String, nullable=False)
    opening_balance = Column(Numeric(12, 2), default=0)
    currency = Column(String, default="EUR")
    account_type = Column(String, nullable=True)

class UserCategory(Base):
    __tablename__ = "user_categories"
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(String, ForeignKey("users.chat_id"), nullable=False)
    name = Column(String, nullable=False)
    monthly_budget = Column(Numeric(12, 2), nullable=True)
```

Le chiavi esterne (ForeignKey) sono:
- `Expense.category_id → user_categories.id`
- `Expense.account_id → accounts.id`
- `Expense.user_id → users.chat_id`

---

## Parte 1 — "Il mio spazio"

**File principale:** `frontend/src/app/spazio/page.tsx`

La pagina è un componente React client-side (`"use client"`) con 5 tab:
**Conti · Categorie · Abbonamenti · Spese · Entrate**

#### Salvataggio (INSERT / UPDATE) — riga 260–290

```tsx
async function handleSave() {
  const { mode, entity, data } = dialog;
  const url = mode === "add"
    ? `/api/space/${ENTITY_PATH[entity]}`
    : `/api/space/${ENTITY_PATH[entity]}/${data.id}`;
  const method = mode === "add" ? "POST" : "PUT";

  const res = await fetch(url, {
    method,
    headers: buildHeaders(),
    body: JSON.stringify(bodyData),
  });
}
```

Un unico handler gestisce sia l'inserimento (POST) che la modifica (PUT). Il percorso API cambia in base all'entità:

| Entità | POST (insert) | PUT (update) |
|--------|--------------|--------------|
| Spesa  | `/api/space/expenses` | `/api/space/expenses/{id}` |
| Entrata | `/api/space/incomes` | `/api/space/incomes/{id}` |
| Conto | `/api/space/accounts` | `/api/space/accounts/{id}` |

#### Eliminazione (DELETE) — righe 296–312

```tsx
async function handleDelete(entity: EntityType, id: number) {
  const res = await fetch(`/api/space/${ENTITY_PATH[entity]}/${id}`, {
    method: "DELETE",
    headers: buildHeaders(),
  });
}
```

#### Proxy Next.js — `frontend/next.config.ts` (righe 16–29)

```ts
async rewrites() {
  return [
    {
      source: "/api/:path*",
      destination: "http://localhost:5000/api/:path*",
    },
  ];
}
```

Tutte le chiamate `/api/*` dal browser vengono inoltrate trasparentemente al server Flask sulla porta 5000. Il browser non sa dell'esistenza di Flask.

### Tab: Conti

#### Frontend — fetch conti

Il fetch dei conti viene effettuato al mount della pagina tramite `fetchAccounts()`, che chiama `/api/space/accounts` con l'header di autenticazione Telegram.

#### Backend Flask — route `/api/space/accounts`

| Metodo | Route | Operazione |
|--------|-------|-----------|
| GET | `/api/space/accounts` | Lista conti dell'utente |
| POST | `/api/space/accounts` | Crea nuovo conto |
| PUT | `/api/space/accounts/{id}` | Modifica conto |
| DELETE | `/api/space/accounts/{id}` | Elimina conto |

#### Query SQL equivalenti

```sql
-- SELECT: leggi conti utente
SELECT * FROM accounts WHERE user_id = :user_id;

-- INSERT: crea conto
INSERT INTO accounts (user_id, name, opening_balance, account_type)
VALUES (:user_id, :name, :opening_balance, :account_type);

-- UPDATE: modifica conto
UPDATE accounts
SET name = :name, opening_balance = :opening_balance, account_type = :account_type
WHERE id = :id AND user_id = :user_id;

-- DELETE: elimina conto
DELETE FROM accounts WHERE id = :id AND user_id = :user_id;
```

---

### Tab: Categorie

#### Backend Flask — route `/api/space/categories`

| Metodo | Route | Operazione |
|--------|-------|-----------|
| GET | `/api/space/categories` | Lista categorie con budget mensile |
| POST | `/api/space/categories` | Crea nuova categoria |
| PUT | `/api/space/categories/{id}` | Modifica categoria (nome e/o budget) |
| DELETE | `/api/space/categories/{id}` | Elimina categoria |

#### Query SQL equivalenti

```sql
-- SELECT: leggi categorie utente
SELECT id, name, monthly_budget FROM user_categories WHERE user_id = :user_id ORDER BY name;

-- INSERT: crea categoria
INSERT INTO user_categories (user_id, name, monthly_budget)
VALUES (:user_id, :name, :monthly_budget);

-- UPDATE: modifica categoria
UPDATE user_categories
SET name = :name, monthly_budget = :monthly_budget
WHERE id = :id AND user_id = :user_id;

-- DELETE: elimina categoria
DELETE FROM user_categories WHERE id = :id AND user_id = :user_id;
```

---

### Tab: Entrate

#### Backend Flask — route `/api/space/incomes`

| Metodo | Route | Operazione |
|--------|-------|-----------|
| GET | `/api/space/incomes` | Lista entrate con paginazione, filtro data, ricerca e ordinamento |
| POST | `/api/space/incomes` | Crea nuova entrata |
| PUT | `/api/space/incomes/{id}` | Modifica entrata |
| DELETE | `/api/space/incomes/{id}` | Elimina entrata |

#### Query SQL equivalenti

```sql
-- SELECT: leggi entrate con conto, paginazione e filtro data
-- Esempio con search="stipendio", income_type="stipendio", sort_by="amount" DESC
SELECT i.id, i.income_date, i.name, i.amount, i.income_type,
       a.name AS account
FROM incomes i
LEFT OUTER JOIN accounts a ON a.id = i.account_id
WHERE i.user_id = :user_id
  AND i.income_date BETWEEN :start AND :end
  AND i.name ILIKE '%stipendio%'        -- solo se search è valorizzato
  AND i.income_type = :income_type      -- solo se income_type è valorizzato
  AND i.account_id = :account_id        -- solo se account_id è valorizzato
ORDER BY i.amount DESC                  -- sort_by + sort_dir dinamici
LIMIT :limit OFFSET :offset;

-- INSERT: inserisci entrata
INSERT INTO incomes (user_id, income_date, amount, name, income_type, account_id)
VALUES (:user_id, :income_date, :amount, :name, :income_type, :account_id);

-- UPDATE: modifica entrata
UPDATE incomes
SET name = :name, amount = :amount, income_date = :date,
    income_type = :income_type, account_id = :account_id
WHERE id = :id AND user_id = :user_id;

-- DELETE: elimina entrata
DELETE FROM incomes WHERE id = :id AND user_id = :user_id;
```

---

### Tab: Spese

#### Frontend — fetch spese con filtri, ordinamento e paginazione

```tsx
const fetchExpenses = useCallback(async (
  page = expPage, rpp = expRowsPP, start = expStart, end = expEnd,
  search = expSearch, catId = expCatId, accId = expAccId,
  sortBy = expSortBy, sortDir = expSortDir,
) => {
  const params = new URLSearchParams({ limit: String(rpp), offset: String(page * rpp), start, end });
  if (search) params.set("search", search);
  if (catId) params.set("category_id", catId);
  if (accId) params.set("account_id", accId);
  params.set("sort_by", sortBy);
  params.set("sort_dir", sortDir);
  const res = await fetch(`/api/space/expenses?${params}`, { headers: buildHeaders() });
  const json = await res.json();
  setExpenses(json.expenses ?? []);
  setExpTotal(json.total ?? 0);
}, [expPage, expRowsPP, expStart, expEnd, expSearch, expCatId, expAccId, expSortBy, expSortDir]);
```

La chiamata costruisce una query string con questi parametri:
- `limit` e `offset` — paginazione
- `start` e `end` — filtro per data (default: primo giorno del mese corrente → oggi)
- `search` — ricerca testuale sulla descrizione (`ILIKE '%testo%'` sul DB)
- `category_id` — filtra per categoria specifica
- `account_id` — filtra per conto specifico
- `sort_by` — colonna di ordinamento (`date` | `amount` | `name`)
- `sort_dir` — direzione (`asc` | `desc`)

Ogni volta che uno dei filtri o l'ordinamento cambia, la pagina viene azzerata a 0 e la fetch viene rilanciata con i nuovi parametri.

#### Frontend — toolbar con ricerca, filtri e ordinamento

```tsx
<TabToolbar label="Spese" onAdd={() => openAdd("expense")} loading={loading.expenses}>
  <SearchInput value={expSearch} onChange={onExpSearch} placeholder="Cerca spesa..." />
  <FilterSelect
    label="Categoria" value={expCatId} onChange={onExpCat}
    options={categories.map(c => ({ value: String(c.id), label: c.name }))}
  />
  <FilterSelect
    label="Conto" value={expAccId} onChange={onExpAcc}
    options={accounts.map(a => ({ value: String(a.id), label: a.name }))}
  />
  <DateRangeFilter start={expStart} end={expEnd} onStart={...} onEnd={...} />
</TabToolbar>
```

Le intestazioni di colonna (Data, Descrizione, Importo) sono cliccabili tramite `TableSortLabel`: il primo click ordina ASC, il secondo DESC, un click su un'altra colonna riparte da ASC.

#### Backend Flask — GET /api/space/expenses

```python
@app.route("/api/space/expenses", methods=["GET"])
@_tg_webapp_auth
def space_expenses_list():
    today = _date.today()
    start = request.args.get("start", _date(today.year, today.month, 1).isoformat())
    end = request.args.get("end", today.isoformat())
    limit = min(int(request.args.get("limit", 25)), 100)
    offset = int(request.args.get("offset", 0))
    search = request.args.get("search") or None
    category_id = int(request.args.get("category_id")) if request.args.get("category_id") else None
    account_id_f = int(request.args.get("account_id")) if request.args.get("account_id") else None
    sort_by = request.args.get("sort_by", "date")     # validato: solo date/amount/name
    sort_dir = request.args.get("sort_dir", "desc")   # validato: solo asc/desc

    start_d = _dt.strptime(start, "%Y-%m-%d").date()
    end_d = _dt.strptime(end, "%Y-%m-%d").date()

    with store.Session() as s:
        pg, err = _pg_or_401(s, g.chat_id)
        items, total = pg.fetch_expenses_paginated(
            start_d, end_d, limit=limit, offset=offset,
            search=search, category_id=category_id, account_id=account_id_f,
            sort_by=sort_by, sort_dir=sort_dir,
        )
        return jsonify({"expenses": items, "total": total})
```

Legge i parametri dalla query string, li valida e li passa al layer di storage.

#### Backend Flask — POST /api/space/expenses — riga 3762

```python
@app.route("/api/space/expenses", methods=["POST"])
@_tg_webapp_auth
def space_expenses_create():
    data = request.json or {}
    exp_date = _dt.strptime(data["date"], "%Y-%m-%d").date()
    result = pg.create_expense(
        expense_date=exp_date,
        amount=float(data["amount"]),
        name=name,
        category_name=data.get("category") or "",
        account_id=data.get("account_id"),
    )
    return jsonify(result), 201
```

#### Backend Flask — PUT /api/space/expenses/{id} — riga 3789

```python
@app.route("/api/space/expenses/<int:expense_id>", methods=["PUT"])
@_tg_webapp_auth
def space_expenses_update(expense_id: int):
    result = pg.update_expense(
        expense_id,
        name=data.get("name") or None,
        amount=float(data["amount"]) if data.get("amount") not in (None, "") else None,
        date=exp_date,
        category_id=int(data["category_id"]) if data.get("category_id") else None,
        account_id=int(data["account_id"]) if data.get("account_id") else None,
    )
    if result is None:
        return jsonify({"error": "Spesa non trovata"}), 404
    return jsonify(result)
```

#### Backend Flask — DELETE /api/space/expenses/{id} — riga 3818

```python
@app.route("/api/space/expenses/<int:expense_id>", methods=["DELETE"])
@_tg_webapp_auth
def space_expenses_delete(expense_id: int):
    ok = pg.delete_expense(expense_id)
    if not ok:
        return jsonify({"error": "Spesa non trovata"}), 404
    return jsonify({"status": "ok"})
```

#### Storage — SELECT con doppio JOIN, filtri dinamici e ordinamento — `fetch_expenses_paginated`

**Codice ORM:**
```python
def fetch_expenses_paginated(
    self, start_date, end_date, limit=25, offset=0,
    search=None, category_id=None, account_id=None,
    sort_by="date", sort_dir="desc",
):
    base_q = (
        self._session.query(Expense, UserCategory, Account)
        .outerjoin(UserCategory, UserCategory.id == Expense.category_id)
        .outerjoin(Account, Account.id == Expense.account_id)
        .filter(
            Expense.user_id == self._user_id,
            Expense.expense_date >= start_date,
            Expense.expense_date <= end_date,
        )
    )
    # Filtri opzionali aggiunti dinamicamente
    if search:
        base_q = base_q.filter(Expense.name.ilike(f"%{search}%"))
    if category_id is not None:
        base_q = base_q.filter(Expense.category_id == category_id)
    if account_id is not None:
        base_q = base_q.filter(Expense.account_id == account_id)

    # Ordinamento dinamico
    _sort_cols = {"date": Expense.expense_date, "amount": Expense.amount, "name": Expense.name}
    sort_col = _sort_cols.get(sort_by, Expense.expense_date)
    order = sort_col.asc() if sort_dir == "asc" else sort_col.desc()

    total = base_q.count()
    rows = base_q.order_by(order).limit(limit).offset(offset).all()
    ...
```

La query fa **due LEFT OUTER JOIN** nella stessa istruzione SQL:
1. `expenses → user_categories` per ottenere il nome della categoria
2. `expenses → accounts` per ottenere il nome del conto

Entrambi sono `OUTER JOIN` (non `INNER`) perché categoria e conto sono campi opzionali — se una spesa non ha categoria o conto, la riga viene comunque restituita con `cat = None` / `acc = None`.

Il `total = base_q.count()` viene eseguito **prima** di `.limit().offset()` in modo da contare tutte le righe filtrate, non solo la pagina corrente. Questo è il valore usato dal componente `TablePagination` per sapere quante pagine ci sono in totale.

**SQL equivalente (esempio con search="sushi", sort_by="amount", sort_dir="asc"):**
```sql
SELECT
    e.id, e.expense_date, e.name, e.amount, e.category_id, e.account_id,
    uc.name AS category, a.name AS account
FROM expenses e
LEFT OUTER JOIN user_categories uc ON uc.id = e.category_id
LEFT OUTER JOIN accounts a         ON a.id  = e.account_id
WHERE e.user_id = :user_id
  AND e.expense_date >= :start_date
  AND e.expense_date <= :end_date
  AND e.name ILIKE '%sushi%'
ORDER BY e.amount ASC
LIMIT :limit OFFSET :offset;

-- Eseguita in anticipo per la paginazione:
SELECT COUNT(*) FROM expenses e ... WHERE e.name ILIKE '%sushi%';
```

**Perché `ILIKE` invece di `LIKE`:**
`ILIKE` è un'estensione PostgreSQL che esegue il pattern matching **case-insensitive** senza dover applicare `LOWER()` su entrambi i lati. SQLAlchemy la genera automaticamente con `.ilike()`.

#### Storage — INSERT — `create_expense` (riga 144)

**Codice ORM:**
```python
def create_expense(self, expense_date, amount, name, category_name, account_id, ...):
    resolved_category_id = self._resolve_category_id(category_name)
    acc_id_int = int(account_id) if account_id is not None else None

    expense = Expense(
        user_id=self._user_id,
        expense_date=expense_date,
        amount=amount,
        name=name,
        category_name=category_name,
        category_id=resolved_category_id,
        account_id=acc_id_int,
    )
    self._session.add(expense)
    self._session.commit()
```

**SQL equivalente:**
```sql
INSERT INTO expenses (user_id, expense_date, amount, name, category_name, category_id, account_id, created_at)
VALUES (:user_id, :expense_date, :amount, :name, :category_name, :category_id, :account_id, NOW());
```

#### Storage — UPDATE — `update_expense` (riga 543)

**Codice ORM:**
```python
def update_expense(self, expense_id, **kwargs):
    row = self._session.query(Expense).filter(
        Expense.id == expense_id,
        Expense.user_id == self._user_id,
    ).first()
    if not row:
        return None
    if "name" in kwargs and kwargs["name"] is not None:
        row.name = kwargs["name"]
    if "amount" in kwargs and kwargs["amount"] is not None:
        row.amount = kwargs["amount"]
    if "date" in kwargs and kwargs["date"] is not None:
        row.expense_date = kwargs["date"]
    if "category_id" in kwargs:
        row.category_id = kwargs["category_id"]
    if "account_id" in kwargs:
        row.account_id = kwargs["account_id"]
    self._session.commit()
```

**SQL equivalente:**
```sql
UPDATE expenses
SET name = :name,
    amount = :amount,
    expense_date = :date,
    category_id = :category_id,
    account_id = :account_id
WHERE id = :expense_id
  AND user_id = :user_id;
```

#### Storage — DELETE — `delete_expense` (riga 564)

**Codice ORM:**
```python
def delete_expense(self, expense_id):
    row = self._session.query(Expense).filter(
        Expense.id == expense_id,
        Expense.user_id == self._user_id,
    ).first()
    if not row:
        return False
    self._session.delete(row)
    self._session.commit()
    return True
```

**SQL equivalente:**
```sql
DELETE FROM expenses
WHERE id = :expense_id
  AND user_id = :user_id;
```

---

### Tab: Abbonamenti e Categorie — filtri client-side

A differenza di Spese e Entrate, Abbonamenti e Categorie caricano **tutti i dati in memoria** al mount (dataset piccolo, nessuna paginazione). Il filtraggio e l'ordinamento avvengono quindi interamente nel browser, senza chiamate aggiuntive al backend.

**Pattern usato:** `useMemo` — ricalcola la lista derivata ogni volta che cambiano i dati o i filtri:

```tsx
const filteredSubs = useMemo(() => {
  const q = subSearch.toLowerCase();
  let r = subscriptions
    .filter(s => s.name.toLowerCase().includes(q))  // ricerca per nome
    .filter(s => !subType || s.sub_type === subType); // filtro per tipo
  r = [...r].sort((a, b) => {
    const v = subSortBy === "amount"
      ? (a.amount ?? 0) - (b.amount ?? 0)
      : a.name.localeCompare(b.name, "it");
    return subSortDir === "asc" ? v : -v;
  });
  return r;
}, [subscriptions, subSearch, subType, subSortBy, subSortDir]);
```

`useMemo` è un hook React che memorizza il risultato di una computazione costosa e lo ricalcola solo quando cambiano le dipendenze dichiarate nell'array `[...]`. Qui il sorting avviene in-memory, nessuna query SQL aggiuntiva.

Lo stesso pattern viene applicato a `filteredCats` per le categorie (ricerca per nome + sort per nome o budget mensile).

---

### Nuovi componenti UI riutilizzabili

Tre componenti estratti in fondo a `page.tsx` per evitare duplicazione nei 4 render:

| Componente | Cosa fa |
|---|---|
| `SearchInput` | Input testo per ricerca — chiama `onChange` ad ogni keystroke |
| `FilterSelect` | Dropdown MUI con opzione "Tutti" — chiama `onChange` al cambio |
| `SortableHead` | `TableCell` con `TableSortLabel` MUI — gestisce frecce ↑↓ e click per sort |

**`SortableHead`** riceve come props la colonna attiva (`sortBy`) e la direzione (`sortDir`). Se la colonna di questa intestazione è quella attiva, mostra la freccia; al click chiama `onSort(field)`. Il componente che gestisce il click all'interno di `renderExpenses`:

```tsx
function handleExpSort(field: string) {
  // Se clicco la stessa colonna → inverto la direzione
  // Se clicco una nuova colonna → parto sempre da "asc"
  const newDir = expSortBy === field
    ? (expSortDir === "asc" ? "desc" : "asc")
    : "asc";
  setExpSortBy(field);
  setExpSortDir(newDir);
  setExpPage(0);  // reset paginazione
  fetchExpenses(0, expRowsPP, expStart, expEnd, expSearch, expCatId, expAccId, field, newDir);
}
```

**Mobile-first:** tutti i controlli nella toolbar usano `flexWrap: "wrap"`. Su schermi stretti il label + pulsante "Aggiungi" rimangono sulla prima riga (il label ha `flexGrow: 1`), mentre i filtri scorrono sotto. I `FilterSelect` hanno `width: { xs: "100%", sm: 130 }` per occupare tutta la larghezza su mobile.

---

## Parte 2 — Inserimento transazioni via chat

### Flusso completo

```
Utente scrive "Ho speso 24€ per il sushi"
    │
    ▼
ChatPage.sendMessage()                      [chat/page.tsx:253]
    │  POST /api/chat/message  { text }
    ▼
Flask: api_chat_message()                   [app.py:2108]
    │  chiama _chat_parse_text()
    ▼
_chat_parse_text()                          [app.py:2005]
    │  1. valida lunghezza messaggio
    │  2. controlla rate limit
    │  3. controlla quota token utente
    │  4. sanitizza input (anti-prompt-injection)
    │  5. carica categorie dell'utente dal DB
    │  6. chiama ExpenseParser (Mistral AI)
    ▼
ExpenseParser.parse_with_usage()            [src/expense_parser.py]
    │  risponde con: { type, amount, category, name, date }
    ▼
_build_parse_reply()                        [app.py:2081]
    │  costruisce testo di anteprima per l'utente
    ▼
risposta al frontend: { ok, type, parsed, reply, saved: false }
    │
    ▼
ChatPage: mostra anteprima + bottoni "Conferma / Annulla"   [chat/page.tsx:521]
    │
    │  Utente clicca ✅ Conferma
    ▼
handleConfirm()                             [chat/page.tsx:199]
    │  POST /api/chat/confirm  { parsed }
    ▼
Flask: api_chat_confirm()                   [app.py:2159]
    │  chiama storage.create_expense() o storage.create_income()
    ▼
PostgresStorage.create_expense()            [postgres_storage.py:144]
    │  INSERT INTO expenses ...
    ▼
PostgreSQL
```

---

### 2.1 Frontend — invio messaggio testuale

**File:** `frontend/src/app/chat/page.tsx`

#### sendMessage — riga 253

```tsx
const sendMessage = useCallback(async (text: string) => {
  const userMsg: Message = {
    id: `user-${Date.now()}`,
    role: "user",
    text: trimmed,
    timestamp: new Date(),
    status: "sending",
  };

  setMessages((prev) => [...prev, userMsg]);  // mostra subito il messaggio
  setIsLoading(true);
  setShowTypingIndicator(true);

  const res = await fetch("/api/chat/message", {
    method: "POST",
    headers: { "Content-Type": "application/json", ...buildHeaders() },
    body: JSON.stringify({ text: trimmed }),
  });
  const data = await res.json();
  handleParseResponse(data, userMsg.id);
}, [isLoading, handleParseResponse]);
```

#### handleParseResponse — riga 166

```tsx
const handleParseResponse = useCallback((data, userMsgId) => {
  const botMsg: Message = {
    id: `bot-${Date.now()}`,
    role: "bot",
    text: data.reply || "Non ho capito...",
    parsed: data.parsed,
    // awaitingConfirm = true solo se il parsing è andato a buon fine
    // e il server non ha ancora salvato (saved = false)
    awaitingConfirm: data.ok && data.type !== "unknown" && data.type !== "error" && !data.saved,
  };
  setMessages((prev) => [...prev, botMsg]);
}, []);
```

#### handleConfirm — riga 199

```tsx
const handleConfirm = useCallback(async (botMsgId, parsed) => {
  // Disabilita subito i bottoni
  setMessages((prev) =>
    prev.map((m) => (m.id === botMsgId ? { ...m, awaitingConfirm: false } : m))
  );

  const res = await fetch("/api/chat/confirm", {
    method: "POST",
    headers: { "Content-Type": "application/json", ...buildHeaders() },
    body: JSON.stringify({ parsed }),   // manda i dati già parsati dall'AI
  });
  const data = await res.json();

  const confirmMsg: Message = {
    id: `confirm-${Date.now()}`,
    role: "bot",
    text: data.reply || "✅ Registrato!",
    status: "sent",
  };
  setMessages((prev) => [...prev, confirmMsg]);
  setMoneoState("happy");
}, []);
```

#### Messaggi vocali — riga 309

```tsx
const handleMicClick = async () => {
  const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
  const recorder = new MediaRecorder(stream);

  recorder.onstop = async () => {
    const blob = new Blob(audioChunksRef.current, { type: "audio/webm" });
    const formData = new FormData();
    formData.append("audio", blob, "voice.webm");

    const res = await fetch("/api/chat/voice", {
      method: "POST",
      headers: buildHeaders(),
      body: formData,      // invia il file audio come multipart
    });
    const data = await res.json();
    // data.transcription contiene il testo trascritto dall'AI
    handleParseResponse(data, userMsg.id);
  };

  recorder.start();
};
```

#### Foto scontrino — riga 400

```tsx
const handleFileChange = async (e) => {
  const file = e.target.files?.[0];
  const formData = new FormData();
  formData.append("image", file);

  const res = await fetch("/api/chat/photo", {
    method: "POST",
    headers: buildHeaders(),
    body: formData,      // invia l'immagine come multipart
  });
  const data = await res.json();
  handleParseResponse(data, userMsg.id);
};
```

---

### 2.2 Backend Flask — parsing e salvataggio

**File:** `src/dashboard/app.py`

#### _chat_parse_text — riga 2005

Funzione helper condivisa da testo, voce e foto.

```python
def _chat_parse_text(chat_id, text, skip_length_check=False):
    # 1. Validazione lunghezza
    if not skip_length_check and len(text) > Config.MAX_MESSAGE_LEN:
        return None, None, "⚠️ Messaggio troppo lungo!"

    # 2. Rate limiting (sliding window 10 msg/min)
    if is_rate_limited(chat_id, max_messages=Config.MAX_MESSAGES_PER_MINUTE):
        return None, None, "⏳ Stai inviando troppi messaggi."

    # 3. Quota token
    plan = store.get_user_plan(chat_id)
    if plan.get("plan_type") != "pro" and plan.get("tokens_remaining", 0) < 800:
        return None, None, "🔒 Hai esaurito i token mensili."

    # 4. Sanitizzazione anti-prompt-injection
    safe_input = f"[INIZIO INPUT UTENTE]\n{text}\n[FINE INPUT UTENTE]"

    # 5. Carica categorie utente dal DB
    categories = [c["name"] for c in storage.get_categories()]

    # 6. Parsing LLM (Mistral Small 3.1)
    parser = ExpenseParser(categories=categories)
    result, usage = parser.parse_with_usage(safe_input)

    return result, usage, ""
```

#### api_chat_message — riga 2108

Risponde con l'anteprima ma **non salva** ancora. Salvataggio avviene solo dopo conferma.

```python
@app.route("/api/chat/message", methods=["POST"])
def api_chat_message():
    text = (data.get("text") or "").strip()

    result, _usage, error_reply = _chat_parse_text(chat_id, text)

    if result is None:
        return jsonify({"ok": True, "type": "unknown",
                        "reply": "Non ho riconosciuto una transazione...", "saved": False})

    reply, parsed = _build_parse_reply(result)
    # Log preview (non ancora confermata)
    store.log_message(chat_id, source="webapp", role="bot", text=reply, metadata=parsed)

    return jsonify({"ok": True, "type": parsed["type"], "parsed": parsed,
                    "reply": reply, "saved": False})   # saved=False → frontend mostra bottoni conferma
```

#### api_chat_confirm — riga 2159

Riceve i dati già parsati e li salva nel DB.

```python
@app.route("/api/chat/confirm", methods=["POST"])
def api_chat_confirm():
    parsed = data.get("parsed") or {}
    parsed_type = parsed.get("type", "expense")

    # Converte la data da stringa ISO a oggetto date
    tx_date = datetime.strptime(str(raw_date).split("T")[0], "%Y-%m-%d").date()

    with store.Session() as s:
        storage = _build_financial_storage(user, pg_session=s)
        accounts = storage.fetch_accounts()
        default_account_id = accounts[0]["id"] if accounts else None

        if parsed_type == "expense":
            storage.create_expense(
                expense_date=tx_date,
                amount=float(parsed.get("amount") or 0),
                category_name=parsed.get("category") or "Altro",
                name=parsed.get("name") or "Spesa",
                account_id=default_account_id,
            )
        else:
            storage.create_income(
                income_date=tx_date,
                amount=float(parsed.get("amount") or 0),
                income_type=parsed.get("income_type") or "Stipendio",
                name=parsed.get("name") or "Entrata",
                account_id=default_account_id,
            )
```

---

### 2.3 ExpenseParser — parsing AI

**File:** `src/expense_parser.py`

L'`ExpenseParser` invia il testo a **Mistral Small 3.1** (modello AI GDPR-compliant, hosted in EU) con un prompt strutturato che include le categorie dell'utente.

Il modello risponde con un JSON strutturato:
```json
{
  "type": "expense",
  "amount": 24.00,
  "category": "Ristoranti",
  "name": "Sushi",
  "date": "2026-06-14"
}
```

---

## Parte 3 — Analytics

### 3.1 Panoramica della pagina

**File:** `frontend/src/app/analytics/page.tsx`

La pagina Analytics è il cruscotto statistico dell'utente. Mostra grafici e tabelle sulle finanze personali. È organizzata in **5 tab**:

| Tab | Contenuto |
|-----|-----------|
| 📈 Panoramica | Andamento capitale, risparmio mensile, tasso di risparmio, spesa per conto |
| 💳 Spese | Trend per categoria, torta categorie, top 5 categorie, top merchant, media categorie, confronto mensile |
| 💰 Entrate | Entrate mensili, capitale per conto (torta) |
| 📋 Lista | Tabella transazioni filtrabile con paginazione |
| 🎯 Budget | Stato avanzamento budget per categoria (solo Pro) |

Alcune funzionalità sono riservate agli utenti **Pro**: storico fino a 24 mesi, filtri avanzati, tasso di risparmio, confronto mensile, stato budget. Gli utenti Free vedono queste sezioni sfocate con un badge "PRO" sovrapposto (`PremiumGate`).

---

### 3.2 Tipi dati (righe 20–56)

```tsx
interface SavingsEntry   { month: string; income: number; expenses: number; net: number }
interface CategoryEntry  { month: string; name: string; amount: number; budget?: number }
interface TransactionEntry {
  id: number; date: string; name: string; amount: number;
  category: string; account: string;
}
interface BudgetStatusEntry {
  category: string; budget: number; spent: number; remaining: number; percentage: number
}
```

Ogni interfaccia corrisponde a un blocco di dati restituito da un endpoint Flask dedicato.

---

### 3.3 Fetch dati — loadData (riga 902)

Al mount della pagina (o quando cambia il numero di mesi nello slider), vengono lanciati **6 fetch in parallelo** con `Promise.all`:

```tsx
const [ov, cat, inc, wea, cap, mer] = await Promise.all([
  fetchApi<OverviewData>("/api/analytics/overview", id, { months: monthStr }),
  fetchApi<CategoriesData>("/api/analytics/categories-expense", id, { months: monthStr }),
  fetchApi<IncomeData>("/api/analytics/income", id, { months: monthStr }),
  fetchApi<WealthData>("/api/analytics/wealth", id, {}),
  fetchApi<CapitalTrendData>("/api/analytics/capital-trend", id, { months: monthStr }),
  fetchApi<TopMerchantsData>("/api/analytics/top-merchants", id, { months: monthStr, limit: "10" }),
]);
```

Se l'utente è Pro, dopo questi 6 vengono caricati altri 3 endpoint riservati:

```tsx
if (pt === "pro") {
  const [bud, sr, mc] = await Promise.all([
    fetchApi<BudgetStatusData>("/api/analytics/budget-status", id, {}),
    fetchApi<SavingsRateData>("/api/analytics/savings-rate", id, { months: monthStr }),
    fetchApi<MonthComparisonData>("/api/analytics/month-comparison", id, {}),
  ]);
}
```

---

### 3.4 Slider periodo (righe 154–185)

```tsx
function PeriodSlider({ value, onChange, maxMonths, actualMonths }) {
  // Free: max 6 mesi — Pro: max 24 mesi
  return (
    <Slider
      value={value}
      min={1} max={maxMonths} step={1}
      onChange={(_, v) => onChange(v as number)}
    />
  );
}
```

Quando l'utente sposta lo slider, `handleMonthsChange` aggiorna lo stato `months`, il `useEffect` si attiva e richiama `loadData` con il nuovo valore — tutti i grafici si aggiornano di conseguenza.

---

### 3.5 Aggregazioni lato client (righe 119–148)

Alcune elaborazioni avvengono **nel browser** dopo aver ricevuto i dati grezzi dal server:

```tsx
// Trasforma righe (month, account, amount) in colonne per il BarChart
function pivotByAccount(rows: AccountMonthEntry[]) {
  const map = new Map<string, Record<string, number>>();
  for (const r of rows) {
    if (!map.has(r.month)) map.set(r.month, {});
    map.get(r.month)![r.account] += r.amount;
  }
  return Array.from(map.entries()).map(([month, vals]) => ({ month, ...vals }));
}

// Prende le 5 categorie con spesa totale maggiore
function pivotTopCategories(rows: CategoryEntry[]) {
  const totals: Record<string, number> = {};
  for (const r of rows) totals[r.name] += r.amount;
  const top5 = Object.entries(totals).sort((a, b) => b[1] - a[1]).slice(0, 5).map(([n]) => n);
  // ... pivot per mese delle sole top 5
}
```

Il server restituisce dati per riga (una riga = un mese + una categoria), il client li "pivota" in strutture adatte ai grafici recharts (una riga = un mese, con colonne per ogni categoria/conto).

---

### 3.6 Componenti grafici

Ogni grafico è un componente React autonomo che riceve i dati come props. Tutti usano la libreria **recharts** con `ResponsiveContainer` per adattarsi allo schermo.

| Componente | Grafico | Dati sorgente |
|---|---|---|
| `SavingsChart` | BarChart (entrate / uscite / netto) | `overview.savings` |
| `CapitalTrendChart` | ComposedChart (area + linee per conto) | `/api/analytics/capital-trend` |
| `CategoryTrendChart` | LineChart (andamento categorie selezionate) | `categories.by_category` |
| `CategoryPieChart` | PieChart (distribuzione categorie ultimo mese) | `categories.by_category` |
| `CategoryHistoryChart` | BarChart (top 5 categorie storiche) | `categories.by_category` |
| `CategoryAvgChart` | BarChart orizzontale (media spesa per categoria) | `categories.averages` |
| `IncomeChart` | BarChart (entrate mensili) | `income.monthly` |
| `WealthPieChart` | PieChart (capitale per conto) | `wealth.accounts` |
| `TopMerchantsChart` | BarChart orizzontale (top merchant) | `/api/analytics/top-merchants` |
| `BudgetGaugeList` | LinearProgress per categoria | `/api/analytics/budget-status` |
| `SavingsRateChart` | ComposedChart (tasso % o valore €, toggle) | `/api/analytics/savings-rate` |
| `MonthComparisonChart` | BarChart raggruppato (questo mese / scorso / media 3m) | `/api/analytics/month-comparison` |

---

### 3.7 Tabella transazioni con filtri — tab Lista (righe 400–537)

Il componente `TransactionsTable` ha un proprio stato locale per i filtri e ricarica i dati ad ogni cambio:

```tsx
function TransactionsTable({ data, isPro, initData }) {
  const [categoryFilter, setCategoryFilter] = useState("");
  const [accountFilter, setAccountFilter]   = useState("");
  const [startDate, setStartDate]           = useState("");
  const [endDate, setEndDate]               = useState("");

  const load = useCallback(async () => {
    const params: Record<string, string> = {
      limit: String(rowsPerPage),
      offset: String(page * rowsPerPage),
    };
    if (isPro && categoryFilter) params.category = categoryFilter;
    if (isPro && accountFilter)  params.account  = accountFilter;
    if (isPro && startDate)      params.start    = startDate;
    if (isPro && endDate)        params.end      = endDate;

    const d = await fetchApi<TransactionsData>("/api/analytics/transactions", initData, params);
    setTxData(d);
  }, [page, rowsPerPage, categoryFilter, accountFilter, startDate, endDate, isPro, initData]);
}
```

I filtri per data, categoria e conto sono disponibili solo agli utenti Pro.

---

### 3.8 Backend Flask — endpoint analytics

**File:** `src/dashboard/app.py`

Tutti gli endpoint analytics seguono lo stesso schema:
1. Leggono `plan_type` dell'utente per determinare i limiti (6 mesi Free / 24 mesi Pro)
2. Calcolano `start_date` in base al parametro `months`
3. Chiamano i metodi di `PostgresStorage` per leggere i dati grezzi
4. Aggregano i risultati in Python con `defaultdict`
5. Restituiscono JSON

#### Tab Panoramica — GET /api/analytics/overview — riga 2778

```python
@app.route("/api/analytics/overview")
def analytics_overview():
    plan_type = _get_user_plan_type(g.chat_id)
    max_months = 24 if plan_type == "pro" else 6
    months = min(int(request.args.get("months", 6)), max_months)
    start = _start_date_for_months(months)

    with store.Session() as s:
        storage = PostgresStorage(session=s, user_id=g.chat_id)
        transactions = storage.fetch_all_transactions(start, end)   # spese
        incomes = storage.fetch_income(start, end)                  # entrate
        accounts = storage.fetch_accounts()                         # conti

    # Aggrega spese per (anno, mese)
    monthly_expenses: dict[tuple, float] = defaultdict(float)
    for t in transactions:
        key = (t["date"].year, t["date"].month)
        monthly_expenses[key] += t["amount"]

    # Calcola netto mensile
    savings = []
    for key in sorted(all_keys):
        y, m = key
        inc_total = monthly_income.get(key, 0.0)
        exp_total = monthly_expenses.get(key, 0.0)
        savings.append({
            "month": _month_label(y, m),
            "income": inc_total,
            "expenses": exp_total,
            "net": round(inc_total - exp_total, 2),
        })
```

**SQL equivalente:**
```sql
-- Spese per mese
SELECT DATE_TRUNC('month', expense_date) AS mese, SUM(amount) AS totale
FROM expenses
WHERE user_id = :user_id
  AND expense_date BETWEEN :start AND :end
GROUP BY mese
ORDER BY mese;

-- Entrate per mese
SELECT DATE_TRUNC('month', income_date) AS mese, SUM(amount) AS totale
FROM incomes
WHERE user_id = :user_id
  AND income_date BETWEEN :start AND :end
GROUP BY mese
ORDER BY mese;
```

#### Tab Spese — GET /api/analytics/categories-expense — riga 2843

```python
@app.route("/api/analytics/categories-expense")
def analytics_categories_expense():
    transactions = storage.fetch_all_transactions(start, end)
    categories   = storage.get_categories()        # con monthly_budget

    # Aggrega per (anno, mese, categoria)
    monthly_cat: dict[tuple, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    for t in transactions:
        key = (t["date"].year, t["date"].month)
        cat = t.get("category") or "Altro"
        monthly_cat[key][cat] += t["amount"]

    # Media per categoria
    averages = [
        {"name": cat, "avg": round(sum(vals) / len(vals), 2)}
        for cat, vals in cat_totals.items()
    ]
```

**SQL equivalente:**
```sql
-- Spese per mese e categoria
SELECT
    DATE_TRUNC('month', e.expense_date) AS mese,
    uc.name AS categoria,
    SUM(e.amount) AS totale
FROM expenses e
LEFT OUTER JOIN user_categories uc ON uc.id = e.category_id
WHERE e.user_id = :user_id
  AND e.expense_date BETWEEN :start AND :end
GROUP BY mese, uc.name
ORDER BY mese;

-- Media per categoria
SELECT uc.name AS categoria, AVG(monthly_total) AS media
FROM (
    SELECT DATE_TRUNC('month', e.expense_date) AS mese,
           uc.name,
           SUM(e.amount) AS monthly_total
    FROM expenses e
    LEFT OUTER JOIN user_categories uc ON uc.id = e.category_id
    WHERE e.user_id = :user_id
      AND e.expense_date BETWEEN :start AND :end
    GROUP BY mese, uc.name
) sub
GROUP BY uc.name
ORDER BY media DESC;
```

#### Tab Panoramica — GET /api/analytics/capital-trend — riga 2971

Calcola il **saldo cumulativo** di tutti i conti mese per mese, partendo dall'`opening_balance` e applicando entrate/uscite in sequenza cronologica.

```python
@app.route("/api/analytics/capital-trend")
def analytics_capital_trend():
    # Fetch tutti i dati storici dall'origine dei tempi
    transactions = storage.fetch_all_transactions(date(2000, 1, 1), end)
    incomes      = storage.fetch_income(date(2000, 1, 1), end)
    accounts     = storage.fetch_accounts()   # contiene opening_balance

    # Inizializza saldi con l'opening_balance di ogni conto
    running_totals = {a["id"]: a["opening_balance"] for a in accounts}

    # Itera mese per mese in ordine cronologico
    for ogni mese in sequenza:
        running_totals[aid] += income_del_mese
        running_totals[aid] -= expense_del_mese
        total_balance = sum(running_totals.values())
        capital_trend.append({"month": ..., "total": total_balance})
```

Non esiste una singola query SQL equivalente per questo calcolo — richiede un **running total** progressivo che il codice Python esegue come un loop mese per mese.

**SQL equivalente approssimativo (con window function):**
```sql
SELECT
    DATE_TRUNC('month', data) AS mese,
    SUM(variazione) OVER (ORDER BY DATE_TRUNC('month', data)) + :opening_balance_totale AS capitale
FROM (
    SELECT income_date AS data,  amount AS variazione FROM incomes  WHERE user_id = :user_id
    UNION ALL
    SELECT expense_date AS data, -amount AS variazione FROM expenses WHERE user_id = :user_id
) movimenti
ORDER BY mese;
```

#### Tab Lista — GET /api/analytics/transactions — riga 3156

Lista transazioni con filtri opzionali per data, categoria e conto, con paginazione.

```python
@app.route("/api/analytics/transactions")
def analytics_transactions():
    max_limit = 500 if is_pro else 50
    limit = min(int(request.args.get("limit", 50)), max_limit)
    offset = int(request.args.get("offset", 0))

    # Free: solo ultimi 30 giorni. Pro: qualsiasi intervallo
    start_date = today - timedelta(days=30) if not is_pro else ...

    transactions = storage.fetch_all_transactions(start_date, end_date)
    accounts     = storage.fetch_accounts()
    acc_map = {a["id"]: a["name"] for a in accounts}

    # Filtra in Python per categoria e conto
    enriched = []
    for t in transactions:
        acc_name = acc_map.get(t.get("account_id"), "Altro")
        cat = t.get("category") or "Altro"
        if category_filter and cat.lower() != category_filter.lower():
            continue
        if account_filter and acc_name.lower() != account_filter.lower():
            continue
        enriched.append({...})

    # Paginazione in Python
    page = enriched[offset:offset + limit]
```

**SQL equivalente:**
```sql
SELECT
    e.id, e.expense_date, e.name, e.amount,
    uc.name AS category,
    a.name  AS account
FROM expenses e
LEFT OUTER JOIN user_categories uc ON uc.id = e.category_id
LEFT OUTER JOIN accounts a         ON a.id  = e.account_id
WHERE e.user_id = :user_id
  AND e.expense_date BETWEEN :start_date AND :end_date
  AND (uc.name = :category OR :category = '')
  AND (a.name  = :account  OR :account  = '')
ORDER BY e.expense_date DESC, e.created_at DESC
LIMIT :limit OFFSET :offset;
```

#### Tab Budget — GET /api/analytics/budget-status — riga 3075 (solo Pro)

```python
@app.route("/api/analytics/budget-status")
def analytics_budget_status():
    # Solo Pro
    if plan_type != "pro":
        return jsonify({"error": "Funzionalita' riservata agli utenti Pro", ...})

    transactions = storage.fetch_all_transactions(month_start, month_end)
    categories   = storage.get_categories()

    budget_map = {c["name"]: (c.get("monthly_budget") or 0.0) for c in categories}
    spent_by_cat: dict[str, float] = defaultdict(float)
    for t in transactions:
        spent_by_cat[t.get("category") or "Altro"] += t["amount"]

    budget_status = [
        {
            "category": cat_name,
            "budget": budget,
            "spent": spent,
            "remaining": max(budget - spent, 0),
            "percentage": round((spent / budget) * 100, 1),
        }
        for cat_name, budget in budget_map.items() if budget > 0
    ]
```

**SQL equivalente:**
```sql
SELECT
    uc.name                           AS category,
    uc.monthly_budget                 AS budget,
    COALESCE(SUM(e.amount), 0)        AS spent,
    GREATEST(uc.monthly_budget - COALESCE(SUM(e.amount), 0), 0) AS remaining,
    ROUND(COALESCE(SUM(e.amount), 0) / uc.monthly_budget * 100, 1) AS percentage
FROM user_categories uc
LEFT OUTER JOIN expenses e
    ON e.category_id = uc.id
    AND e.user_id = :user_id
    AND e.expense_date BETWEEN :month_start AND :month_end
WHERE uc.user_id = :user_id
  AND uc.monthly_budget > 0
GROUP BY uc.name, uc.monthly_budget
ORDER BY percentage DESC;
```

#### Tab Spese — GET /api/analytics/top-merchants — riga 3247

```python
@app.route("/api/analytics/top-merchants")
def analytics_top_merchants():
    transactions = storage.fetch_all_transactions(start, end)

    merchant_totals: dict[str, float] = defaultdict(float)
    merchant_counts: dict[str, int]   = defaultdict(int)
    for t in transactions:
        name = t.get("name", "Sconosciuto").strip()
        merchant_totals[name] += t["amount"]
        merchant_counts[name] += 1

    top = sorted(merchant_totals.items(), key=lambda x: x[1], reverse=True)[:limit]
```

**SQL equivalente:**
```sql
SELECT
    e.name                AS merchant,
    SUM(e.amount)         AS totale,
    COUNT(*)              AS occorrenze,
    MAX(uc.name)          AS categoria_prevalente
FROM expenses e
LEFT OUTER JOIN user_categories uc ON uc.id = e.category_id
WHERE e.user_id = :user_id
  AND e.expense_date BETWEEN :start AND :end
GROUP BY e.name
ORDER BY totale DESC
LIMIT :limit;
```

#### Tab Panoramica — GET /api/analytics/savings-rate — riga 3300 (solo Pro)

Calcola `(entrate - uscite) / entrate * 100` mese per mese.

```python
for key in all_keys:
    inc = monthly_income.get(key, 0.0)
    exp = monthly_expenses.get(key, 0.0)
    savings = round(inc - exp, 2)
    rate = round((savings / inc) * 100, 1) if inc > 0 else 0.0
```

**SQL equivalente:**
```sql
WITH mese_income AS (
    SELECT DATE_TRUNC('month', income_date) AS mese, SUM(amount) AS totale_entrate
    FROM incomes WHERE user_id = :user_id AND income_date BETWEEN :start AND :end
    GROUP BY mese
),
mese_expense AS (
    SELECT DATE_TRUNC('month', expense_date) AS mese, SUM(amount) AS totale_uscite
    FROM expenses WHERE user_id = :user_id AND expense_date BETWEEN :start AND :end
    GROUP BY mese
)
SELECT
    COALESCE(i.mese, e.mese) AS mese,
    COALESCE(i.totale_entrate, 0)   AS income,
    COALESCE(e.totale_uscite, 0)    AS expenses,
    COALESCE(i.totale_entrate, 0) - COALESCE(e.totale_uscite, 0) AS savings,
    CASE WHEN COALESCE(i.totale_entrate, 0) > 0
         THEN ROUND(
             (COALESCE(i.totale_entrate, 0) - COALESCE(e.totale_uscite, 0))
             / COALESCE(i.totale_entrate, 0) * 100, 1)
         ELSE 0 END AS rate
FROM mese_income i
FULL OUTER JOIN mese_expense e ON i.mese = e.mese
ORDER BY mese;
```

#### Tab Spese — GET /api/analytics/month-comparison — riga 3359 (solo Pro)

Confronta la spesa del mese corrente con il mese precedente e la media degli ultimi 3 mesi completi, per ogni categoria.

```python
# Mese corrente
cur_spending = monthly_cat.get((current_year, current_month), {})

# Mese precedente
prev_spending = monthly_cat.get(prev_key, {})

# Media ultimi 3 mesi completi
past_keys = [k for k in all_keys if k != cur_key][-3:]
for k in past_keys:
    for cat, amount in monthly_cat[k].items():
        avg_spending[cat] += amount
for cat in avg_spending:
    avg_spending[cat] /= len(past_keys)

# Calcola variazione %
change_pct = round(((cur_val - prev_val) / prev_val) * 100, 1) if prev_val > 0 else 0.0
```

**SQL equivalente:**
```sql
WITH cat_monthly AS (
    SELECT
        DATE_TRUNC('month', e.expense_date) AS mese,
        COALESCE(uc.name, 'Altro')          AS categoria,
        SUM(e.amount)                        AS totale
    FROM expenses e
    LEFT OUTER JOIN user_categories uc ON uc.id = e.category_id
    WHERE e.user_id = :user_id
      AND e.expense_date >= :history_start
    GROUP BY mese, categoria
)
SELECT
    categoria,
    MAX(CASE WHEN mese = DATE_TRUNC('month', CURRENT_DATE) THEN totale ELSE 0 END) AS current_month,
    MAX(CASE WHEN mese = DATE_TRUNC('month', CURRENT_DATE) - INTERVAL '1 month' THEN totale ELSE 0 END) AS last_month,
    AVG(CASE WHEN mese < DATE_TRUNC('month', CURRENT_DATE) THEN totale END) AS avg_3m
FROM cat_monthly
GROUP BY categoria
ORDER BY categoria;
```
