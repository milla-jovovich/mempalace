# MemPalace: Палац Пам'яті для AI

## Повний технічний розбір архітектури, Pull Requests та науки запам'ятовування

**Автор:** Ruslan Popescu | **Дата:** Квітень 2026
**Репозиторій:** github.com/MemPalace/mempalace
**Цільова аудиторія:** iOS-розробник, який хоче зрозуміти Python/ChromaDB систему

---

# Частина I: Чому це працює — Наука Палацу Пам'яті

## 1.1. Метод Локусів: від Симоніда до нейронауки

У 477 році до н.е. грецький поет Симонід із Кеосу вижив після обвалу бенкетного залу. Він зміг ідентифікувати загиблих гостей, тому що запам'ятав, де кожен сидів. Цей випадок народив **метод локусів** (Method of Loci) — техніку, яку Аристотель систематизував у трактаті «Про пам'ять та пригадування» (*De Memoria et Reminiscentia*).

Суть техніки: уяви знайомий простір — будинок, вулицю, маршрут. Розмісти інформацію, яку хочеш запам'ятати, у конкретних місцях цього простору. Щоб пригадати — подумки пройди маршрутом.

Мета-аналіз 2025 року (Ondřej et al., *British Journal of Psychology*) показав **великий ефект** (d = 0.88) методу локусів на негайне серійне пригадування порівняно з простим повторенням. Нейровізуалізаційні дослідження (bioRxiv, лютий 2025) виявили, що метод локусів створює **унікальні нейронні патерни** в префронтальній корі, нижній скроневій та задній тім'яній ділянках. Що важливо — ці патерни були різними у різних людей, але стабільними у кожного окремо, що корелювало з кращим запам'ятовуванням через 4 місяці.

Ключовий механізм: метод зменшує **проактивну інтерференцію** — коли раніше вивчений матеріал заважає пригадати новий. Просторова прив'язка створює унікальний контекст для кожного фрагменту інформації, тому вони не "злипаються" в пам'яті.

## 1.2. Чому це працює для AI: від людської пам'яті до векторних баз

Дослідники AI-пам'яті категоризують пам'ять агентів так само, як психологи категоризують людську пам'ять:

**Людська пам'ять → AI аналог:**

- **Сенсорна (мілісекунди)** → Поточний промпт/контекстне вікно
- **Короткострокова/Робоча (секунди-хвилини)** → Контекстне вікно LLM (200K токенів у Claude)
- **Довгострокова епізодична (роки)** → Векторна база даних з конкретними фрагментами розмов/подій
- **Довгострокова семантична (факти)** → Граф знань (Knowledge Graph) з сутностями та зв'язками
- **Процедурна (навички)** → Системні промпти, інструкції, протоколи

MemPalace реалізує всі три типи довгострокової пам'яті:

1. **Епізодична** — ChromaDB drawers з фрагментами розмов та файлів (коли? де? що говорили?)
2. **Семантична** — SQLite Knowledge Graph з темпоральними трійками (хто? що робить? з коли?)
3. **Процедурна** — AAAK-інструкції та Protocol Injection через MCP

### Чому саме векторний пошук?

Коли ти шукаєш в Core Data, ти пишеш предикат: `NSPredicate(format: "name == %@", "Alice")`. Це **точний пошук** — або є збіг, або ні.

Векторний пошук працює інакше. Текст "Як працюють актори в Swift?" і "Swift concurrency actors async/await" не мають жодного спільного слова (крім "Swift"), але семантично вони близькі. Модель `all-MiniLM-L6-v2` перетворює обидва тексти в 384-мірні вектори, і ці вектори будуть близькими в просторі. ChromaDB знаходить цю близькість за допомогою HNSW-індексу.

Це як людська асоціативна пам'ять: ти не згадуєш речі за точним ключовим словом, а за *змістом* — "щось було про архітектуру акторів... щось таке..."

### 4-рівнева архітектура пам'яті

MemPalace реалізує 4-рівневу систему, натхненну моделлю когнітивного навантаження (Cognitive Load Theory, Sweller 1988):

```
Layer 0: Identity       (~100 токенів)   — Завжди завантажено. "Хто я?"
Layer 1: Essential Story (~500-800)      — Завжди завантажено. Ключові моменти.
Layer 2: On-Demand      (~200-500 кожен) — Завантажується за потреби.
Layer 3: Deep Search    (необмежено)     — Повний семантичний пошук ChromaDB.
```

Вартість пробудження: ~600-900 токенів (L0+L1). Залишає 95%+ контексту вільним. Це як iOS-додаток: ти не завантажуєш всю базу в пам'ять — лише те, що потрібно для поточного View.

## 1.3. Палац Пам'яті як метафора та архітектура

| Класичний концепт | Реалізація в коді | Структура даних |
|---|---|---|
| **Палац** | Директорія ChromaDB на диску | `~/.mempalace/palace/` |
| **Крило** (Wing) | Проєкт або домен | Метадане `wing` на кожному drawer |
| **Кімната** (Room) | Тема всередині крила | Метадане `room` на кожному drawer |
| **Шухляда** (Drawer) | Один фрагмент запам'ятованого контенту | Документ ChromaDB: текст + ембедінг + метадані |
| **Зал** (Hall) | Тип зв'язку між кімнатами | Мітка ребра в графі |
| **Тунель** (Tunnel) | Кімната з однаковою назвою в різних крилах | Обчислюється динамічно |
| **Граф знань** | Фактичні зв'язки (хто/що/коли) | SQLite з сутностями та темпоральними трійками |

Метафора палацу — це не просто красива назва. Вона визначає всю архітектуру API: ти не "записуєш дані" — ти "кладеш в шухляду кімнати крила палацу". Це робить MCP-протокол інтуїтивним для AI-агента, бо він може мислити просторово.

---

# Частина II: Архітектура — Як влаштований MemPalace

## 2.1. Карта модулів (для iOS-розробника)

Уяви, що MemPalace — це iOS-додаток. Тоді модулі можна порівняти так:

| Модуль Python | iOS аналог | Що робить |
|---|---|---|
| `palace.py` | `CoreDataStack` | Доступ до ChromaDB, get_collection(), file_already_mined() |
| `mcp_server.py` | `URLSession` + API Router | JSON-RPC 2.0 сервер з 19+ інструментами |
| `miner.py` | `NSBatchInsertRequest` pipeline | Читає файли проєкту → чанки → ембедінги → ChromaDB |
| `convo_miner.py` | Спеціалізований імпортер | Те ж для експортів чатів (Claude.ai, ChatGPT, Codex, Slack) |
| `normalize.py` | `JSONDecoder` з кількома стратегіями | Авто-детект формату чату → канонічний транскрипт |
| `searcher.py` | `NSFetchedResultsController` | Семантичний пошук з оцінками релевантності |
| `knowledge_graph.py` | Окрема SQLite модель | Темпоральні entity-relationship трійки |
| `palace_graph.py` | Graph traversal | Обхід графа метаданих ChromaDB (wings/rooms/halls/tunnels) |
| `layers.py` | Memory management | 4-рівневий контекстний менеджер |
| `dialect.py` | Кастомний серіалізатор | AAAK — lossy стиснення для щоденникових записів |
| `cli.py` | `AppDelegate` + Command router | Всі CLI-команди: mine, sync, repair, status |
| `hooks_cli.py` | `AppDelegate` lifecycle hooks | Авто-збереження при stop/precompact/session-start |
| `config.py` | `UserDefaults` + Input Sanitizer | Шляхи палацу, санітізація вводу |
| `repair.py` | Corruption recovery | Хірургічний ремонт палацу (scan/prune/rebuild) |
| `dedup.py` | Дедуплікатор | Прибирає дублікати, які роздувають HNSW-індекс |
| `migrate.py` | Core Data migration | Міграція між версіями ChromaDB |
| `query_sanitizer.py` | Input validation | Вирізає contamination від системних промптів |

## 2.2. ChromaDB — Векторне сховище (аналог Core Data + ембедінги)

ChromaDB — це як Core Data, де замість предикатів у тебе семантична близькість.

**Основні концепти:**

- **Collection** = Entity/Table в Core Data. MemPalace використовує одну: `mempalace_drawers`.
- **Document** = Текстовий контент шухляди (чанк файлу або обмін у розмові).
- **Embedding** = 384-float вектор від моделі `all-MiniLM-L6-v2` (ONNX). Два тексти зі схожим змістом дають вектори, близькі в 384-вимірному просторі.
- **Metadata** = Key-value пари поряд з документом: `wing`, `room`, `source_file`, `content_hash`, `filed_at`. Використовуються для фільтрації, НЕ для пошуку.
- **HNSW Index** = Індекс приблизного пошуку найближчих сусідів. Багатошаровий граф, де вузли — вектори, ребра з'єднують близькі вектори. Верхні шари — мало вузлів для швидкої маршрутизації, нижні — всі вузли для точності.
- **Upsert** = Insert-or-update. Ідемпотентна операція — повторний виклик з тими ж даними безпечний. АЛЕ: саме тут криється проблема HNSW.

### Проблема HNSW (чому існує PR #239)

Коли ти робиш `upsert` для документа, який вже існує, C++ бібліотека `hnswlib` викликає `updatePoint`. На macOS ARM (Apple Silicon) це може викликати segfault. Крім того, повторні upsert'и без дедуплікації роздувають `link_lists.bin` (файл HNSW-індексу) — він росте необмежено. На великих палацах може досягти терабайтів.

## 2.3. MCP-протокол — Як AI спілкується з палацом

MCP Server (`mcp_server.py`) — це JSON-RPC 2.0 сервер, написаний вручну (без SDK).

**Транспорт:** Читає JSON зі stdin, пише JSON у stdout. Запускається як subprocess Claude Code.

**24 інструменти** зареєстровані в словнику `TOOLS`, кожен з описом, JSON Schema та handler-функцією:

- **Читання:** `mempalace_status`, `mempalace_search`, `mempalace_list_wings`, `mempalace_list_rooms`, `mempalace_get_taxonomy`, `mempalace_check_duplicate`, `mempalace_get_aaak_spec`, `mempalace_get_drawer`, `mempalace_list_drawers`, `mempalace_sync_status`
- **Запис:** `mempalace_add_drawer`, `mempalace_update_drawer`, `mempalace_delete_drawer`, `mempalace_diary_write`, `mempalace_diary_read`, `mempalace_memories_filed_away`
- **Граф знань:** `mempalace_kg_add`, `mempalace_kg_query`, `mempalace_kg_invalidate`, `mempalace_kg_timeline`, `mempalace_kg_stats`
- **Граф палацу:** `mempalace_traverse`, `mempalace_find_tunnels`, `mempalace_graph_stats`
- **Конфігурація:** `mempalace_hook_settings`

**Write-Ahead Log (WAL):** Кожна операція запису логується в `~/.mempalace/wal/write_log.jsonl` *перед* виконанням. Це аудит-трейл, не crash recovery.

**Protocol Injection:** Перший виклик `mempalace_status` повертає `PALACE_PROTOCOL` і `AAAK_SPEC` прямо у відповіді. Це навчає AI, як використовувати палац, без системного промпту.

## 2.4. Pipeline Майнінгу

### Для файлів проєкту (`mempalace mine <dir>`):

```
1. Обхід дерева директорій (пропускає .git, node_modules, __pycache__ тощо)
2. Для кожного файлу:
   a. Перевірити чи вже замайнено (source_mtime / content_hash) → пропустити
   b. Видалити існуючі drawers для цього файлу (уникає HNSW segfault при upsert)
   c. Прочитати вміст файлу
   d. Обчислити file_content_hash (MD5 stripped content)
   e. Визначити room (шлях директорії → ім'я файлу → scoring ключових слів)
   f. Порізати на чанки ~800 символів з перекриттям 100 символів
   g. Для кожного чанка: add_drawer(collection, wing, room, content, metadata)
      → ChromaDB ембедить текст і зберігає
```

### Для експортів чатів (`mempalace mine <dir> --mode convos`):

```
1. Шукає .json/.jsonl файли
2. normalize(filepath) → авто-детект формату:
   - Claude Code JSONL (type: human/assistant)
   - Codex CLI JSONL (session_meta + event_msg)
   - Claude.ai JSON (sender/role + text/content + chat_messages)
   - ChatGPT JSON (mapping tree traversal)
   - Slack JSON (масив повідомлень)
3. Вихід: канонічний формат "> user\nassistant\n\n"
4. chunk_exchanges() → один drawer на пару Q+A
5. detect_convo_room() → класифікація: technical/architecture/planning/decisions
6. add_drawer() з ingest_mode="convos"
```

## 2.5. AAAK Діалект — Lossy стиснення для щоденника

AAAK — кастомний формат стиснення з втратами. Він НЕ МОЖЕ відновити оригінальний текст.

**Формат:**

```
FILE_NUM|PRIMARY_ENTITY|DATE|TITLE
ZID:ENTITIES|topic_keywords|"key_quote"|WEIGHT|EMOTIONS|FLAGS
T:ZID<->ZID|label
ARC:emotion->emotion->emotion
```

**Приклад:**

```
Z1:ALC,JOR|swift,concurrency,actors|"вирішили використовувати async/await"|8|determ,conf|DECISION,TECHNICAL
```

**Коди емоцій:** vul=вразливість, joy=радість, fear=страх, trust=довіра, grief=горе, wonder=подив, rage=лють, love=любов, hope=надія, despair=відчай, peace=спокій, humor=гумор

**Прапорці:** ORIGIN (початок чогось), CORE (ключове переконання), SENSITIVE (обережно), PIVOT (емоційний поворот), GENESIS (привело до чогось існуючого), DECISION, TECHNICAL

AI навчається цьому формату через `AAAK_SPEC`, що інжектується у відповідь `mempalace_status`.

## 2.6. Граф Знань (Knowledge Graph)

SQLite база для темпоральних entity-relationship трійок:

```python
kg = KnowledgeGraph()
kg.add_triple("Макс", "дитина_від", "Аліса", valid_from="2015-04-01")
kg.add_triple("Макс", "займається", "плаванням", valid_from="2025-01-01")

# Запит: все про Макса
kg.query_entity("Макс")

# Запит: що було вірним про Макса в січні 2026?
kg.query_entity("Макс", as_of="2026-01-15")

# Інвалідація: факт більше не вірний
kg.invalidate("Макс", "has_issue", "sports_injury", ended="2026-02-15")
```

Це конкурує з Zep (Neo4j в хмарі, $25/місяць+). MemPalace використовує SQLite локально (безкоштовно).

---

# Частина III: Pull Requests — Повний розбір

## 3.1. PR #239 — Безпечний Repair (HNSW Index Corruption)

**Гілка:** `fix/chromadb-hnsw-rebuild`
**Файли:** `mempalace/cli.py` (+101 / -26)

### Проблема

ChromaDB зберігає HNSW-індекс у файлі `link_lists.bin`. При повторних upsert'ах (нормальна операція при повторному майнінгу) HNSW додає нові вузли замість дедуплікації. Файл росте необмежено.

Коли HNSW стає corrupt, **навіть `delete_collection()` крашить процес** — бо операція видалення завантажує HNSW сегменти для очищення. Це C-level segfault, не Python exception — ніякий try/except не допоможе.

**Критичний інсайт:** SQLite файл (`chroma.sqlite3`) НЕ пошкоджується. Документи та метадані зберігаються окремо від векторного індексу. Метод `get()` читає з SQLite, обходячи HNSW повністю.

### Старий код (що не працювало)

```python
# BEFORE — це крашить з C-level segfault
client = chromadb.PersistentClient(palace_path)
client.delete_collection("mempalace_drawers")   # SEGFAULT ТУТ
client.create_collection("mempalace_drawers")
```

### Новий код — 6 кроків

**Крок 1 — Читання через `get()`, обхід HNSW:**

```python
client = chromadb.PersistentClient(path=palace_path)
col = client.get_collection("mempalace_drawers")
# get() читає з SQLite, НЕ з HNSW
batch = col.get(limit=500, offset=offset, include=["documents", "metadatas"])
```

Батчі по 500 замість старих 5000 — щоб не OOM на великих палацах.

**Крок 2 — Звільнення файлових дескрипторів:**

```python
del col
del client
gc.collect()
```

Явне видалення змушує ChromaDB закрити всі SQLite/HNSW файли перед маніпуляцією з директоріями.

**Крок 3 — Побудова нового палацу у тимчасовій директорії:**

```python
rebuild_path = palace_path + "_rebuild"
new_client = chromadb.PersistentClient(path=rebuild_path)
new_col = new_client.create_collection("mempalace_drawers")
```

Створює чистий HNSW-індекс. Оригінальний палац повністю НЕ ТОРКАЄТЬСЯ.

**Крок 4 — Запис даних у новий палац:**

```python
new_col.add(documents=batch_docs, ids=batch_ids, metadatas=batch_metas)
```

Батчі по 100. Якщо запис впав — `sys.exit(1)`, оригінал непошкоджений.

**Крок 5 — Верифікація:**

```python
rebuilt_count = new_col.count()
if rebuilt_count != len(all_ids):
    # Abort — оригінал непошкоджений, partial rebuild збережено для інспекції
    return
```

**Крок 6 — Атомарна заміна директорій:**

```python
os.rename(palace_path, backup_path)    # оригінал → .backup
os.rename(rebuild_path, palace_path)   # _rebuild → palace
```

`os.rename` на одній файловій системі — атомарна операція. У жоден момент палац не "відсутній".

### Властивості безпеки

- Оригінальний палац ніколи не мутується під час rebuild
- Верифікація перед swap — невідповідність кількості перериває операцію
- Backup зберігається — стара директорія перейменована, не видалена
- Ніякого контакту з HNSW на corrupted індексі — тільки `get()` (SQLite)
- Захист від trailing slash — `palace_path.rstrip(os.sep)` гарантує правильний шлях backup

### iOS аналогія

Уяви, що твій Core Data SQLite store має corrupt WAL файл, і `NSPersistentStoreCoordinator` крашить на будь-якому записі. Фікс: відкрити SQLite напряму через `sqlite3` (обійшовши Core Data), витягнути всі рядки, створити fresh store, вставити рядки, атомарно замінити `.sqlite` файли.

---

## 3.2. PR #243 — Фікс нормалайзера Claude.ai Chat Export

**Гілка:** `fix/claude-ai-chat-normalizer`
**Файли:** `mempalace/normalize.py` (+39/-11), `tests/test_normalize.py` (+374)

### Проблема

MemPalace може майнити експорти чатів з кількох платформ. Кожна платформа експортує в своєму JSON-форматі. Модуль `normalize.py` авто-детектить формат і конвертує в канонічний транскрипт.

Проблема: Claude.ai використовує **інші назви полів** ніж інші платформи:

| Поле | Claude Code / ChatGPT | Claude.ai Privacy Export |
|------|----------------------|--------------------------|
| Роль відправника | `"role"` | `"sender"` |
| Значення ролі | `"user"` / `"assistant"` | `"human"` / `"assistant"` |
| Тіло повідомлення | `"content"` (рядок або список блоків) | `"text"` (завжди plain string) |

Старий код перевіряв тільки `role` і `content`. Коли приходив Claude.ai export з `sender: "human"` і `text: "..."`:

```
item.get("role", "")    → ""  (пусто — немає збігу)
item.get("content", "") → ""  (пусто — неправильне ім'я поля)
→ Нуль повідомлень → функція повернула None
→ Файл пройшов до raw JSON pass-through → зберігся як непарсений JSON blob
→ Якість пошуку для Claude.ai розмов → практично нуль
```

### Фікс — три зміни

**1. Dual-field витягнення ролі:**

```python
# BEFORE
role = item.get("role", "")

# AFTER
role = item.get("sender") or item.get("role") or ""
```

**2. Dual-field витягнення тексту з null safety:**

```python
# BEFORE
text = _extract_content(item.get("content", ""))

# AFTER
text = (item.get("text") or "").strip() or _extract_content(item.get("content", ""))
```

Пріоритет: `text` спочатку (Claude.ai), потім `content` як fallback. `or ""` обробляє випадок, коли `"text"` = JSON `null` (Python `None`).

**3. Ізоляція транскрипту по розмовах:**

```python
# BEFORE — всі розмови зливались в один плоский транскрипт
for convo in data:
    for item in convo["chat_messages"]:
        all_messages.append(...)

# AFTER — кожна розмова — окрема секція з заголовком
transcripts = []
for convo in data:
    messages = []  # per-conversation
    for item in convo["chat_messages"]:
        messages.append(...)
    header = convo.get("name", "").strip()
    if header:
        transcript = f"--- {header} ---\n\n{transcript}"
    transcripts.append(transcript)
return "\n\n".join(transcripts)
```

**Важливий нюанс:** Якщо формат визначений як Claude.ai, але всі розмови порожні, повертається порожній рядок `""` замість `None`. Це запобігає fallthrough до Slack-парсера, який би з'їв усе що завгодно (найбільш permissive).

### Ланцюг детекції формату

```
1. _try_claude_code_jsonl(content)    ← JSONL з type: human/assistant
2. _try_codex_jsonl(content)          ← JSONL з session_meta guard
3. _try_claude_ai_json(data)          ← Масив розмов з sender/role ← ЦЕПР ФІКСИТЬ
4. _try_chatgpt_json(data)            ← Mapping tree з author.role
5. _try_slack_json(data)              ← Масив message об'єктів (найбільш permissive)
```

### 7 нових тестів

| Тест | Що перевіряє |
|------|-------------|
| `test_claude_ai_sender_field` | `sender: "human"` розпізнається як повідомлення користувача |
| `test_claude_ai_text_field_preferred` | Поле `text` має пріоритет навіть при наявності `content` block list |
| `test_claude_ai_multi_conversation_boundaries` | Кілька розмов → окремі секції, не один blob |
| `test_claude_ai_flat_sender_format` | Плоский список повідомлень з полем `sender` |
| `test_claude_ai_role_field_still_works` | Зворотна сумісність — старий формат `role`/`content` все ще парсить |
| `test_claude_ai_empty_chat_messages` | Розмови з 0 повідомлень пропускаються, не крашать |
| `test_claude_ai_content_block_list_fallback` | Коли `text` пустий, fallback до витягнення з `content` blocks |

### iOS аналогія

Це як фікс `JSONDecoder`, який очікував `CodingKeys` одного API-формату, але інший API надсилає ті ж дані з іншими назвами ключів. Фікс: перевіряти обидва імена ключів через `decodeIfPresent`, gracefully fallback.

---

## 3.3. PR #251 — Sync Command (Інкрементальний Re-Mining)

**Гілка:** `feat/sync-command`
**Файли:** 11 файлів, +1323 / -110

Це найбільший PR. Він додає content hashing до всієї pipeline і нову CLI-команду `mempalace sync`.

### Проблема

Після початкового майнінгу файли змінюються. Палац стає stale — drawers містять застарілий контент. Єдиний варіант — перемайнити все з нуля (`--force`), що повільно на великих палацах.

### Рішення — Content Hash + Incremental Sync

Кожен drawer тепер зберігає `content_hash` (MD5 stripped content файлу-джерела).

```python
def file_content_hash(filepath: Path) -> str:
    content = filepath.read_text(encoding="utf-8", errors="replace").strip()
    return hashlib.md5(content.encode(), usedforsecurity=False).hexdigest()
```

- **Вхід:** Повний вміст файлу, stripped від whitespace
- **Вихід:** 32-символьний hex MD5 digest
- **Зберігається:** У метаданих кожного drawer як `content_hash`
- **Всі чанки одного файлу мають один hash** — це file-level властивість
- Для розмов: hash обчислюється на raw content *перед* normalize() — тому hash завжди відповідає тому, що фізично на диску

### Повний flow команди `mempalace sync`

```
mempalace sync [--dir <dir>] [--clean] [--dry-run]
```

**Крок 1 — Сканування палацу:**

Ітерація по всіх drawers батчами по 500, збір унікальних `source_file` шляхів з їх `content_hash`, drawer IDs, wing, ingest_mode.

**Крок 2 — Фільтр по директорії:**

Якщо `--dir` задано, перевіряються тільки файли під цією директорією. Використовує `Path.resolve()` для коректного порівняння (macOS /var → /private/var symlink).

**Крок 3 — Класифікація кожного файлу:**

| Стан | Умова | Що відбувається |
|------|-------|----------------|
| **Fresh** | Файл існує, hash збігається | Нічого — контент актуальний |
| **Stale** | Файл існує, hash відрізняється | Видалити старі drawers + перемайнити |
| **Missing** | Файл більше не існує на диску | Повідомити; видалити drawers якщо `--clean` |
| **No-hash (legacy)** | Drawer не має `content_hash` (замайнений до цієї фічі) | Повідомити; запропонувати `--force` re-mine |

**Крок 4 — Звіт:**

```
  Fresh (unchanged):     142
  Stale (changed):       3
  Missing (deleted):     1
  No hash (legacy):      28 (re-mine with --force to add hashes)
```

**Крок 5 — Атомарний per-file re-mining:**

Для кожного stale файлу:
1. Видалити всі drawer IDs для цього файлу з ChromaDB
2. Негайно перемайнити цей конкретний файл
3. Маршрутизація до правильного miner за `ingest_mode`: `"convos"` → conversation miner, інакше → project miner

"Атомарний per-file" означає delete+re-mine відбувається один файл за раз. У жоден момент контент файлу не відсутній у палаці довше, ніж час обробки одного файлу.

### Зміни в `miner.py`

**`add_drawer()` тепер використовує `add()` замість `upsert()`:**

```python
# BEFORE
collection.upsert(documents=[content], ids=[drawer_id], metadatas=[metadata])

# AFTER
collection.add(documents=[content], ids=[drawer_id], metadatas=[meta])
```

Це принципова зміна. `upsert()` = "вставити або оновити". `add()` = "вставити, помилка якщо вже існує". Оскільки перед re-mine ми видаляємо старі drawers, дублікати неможливі. А `add()` не торкає HNSW для існуючих записів, уникаючи segfault.

**`process_file()` тепер повертає `int` замість `tuple`:**

```python
# BEFORE
def process_file(...) -> tuple:
    return drawers_added, room

# AFTER
def process_file(...) -> int:
    return drawers_added
```

Room визначається окремо в mining loop, бо тепер `process_file()` може повернути 0 (файл пропущений) без необхідності знати room.

### Зміни в `convo_miner.py`

Додано `filepath_filter` параметр — дозволяє sync перемайнити лише один конкретний файл зі всієї директорії розмов, замість всієї директорії.

Додано `ingest_mode: "convos"` в метадані — sync використовує це, щоб знати який miner викликати при перемайнінгу.

### `--force` на `mempalace mine`

Нова функція `_force_clean()` видаляє ВСІ існуючі drawers для source directory перед майнінгом:

```python
def _force_clean(palace_path: str, source_dir: str):
    source_prefix = str(Path(source_dir).expanduser().resolve())
    # ...iterate all drawers, collect those under source_prefix...
    for i in range(0, len(to_delete), 100):
        col.delete(ids=to_delete[i:i + 100])
```

Це гарантує, що всі drawers отримають `content_hash` — навіть legacy.

### iOS аналогія

Це як `NSPersistentHistoryTracking` в Core Data — відстежування, що змінилось з останнього sync. Але замість відстежування окремих attribute changes, MemPalace відстежує file-level content hashes. Якщо hash відрізняється, весь файл перепроцесовується.

---

## 3.4. PR #256 — Sync Status MCP Tool + Freshness Hook

**Гілка:** `feat/sync-mcp-tool`
**Файли:** 3 файли, +427

### Проблема

PR #251 дає *людині* sync команду. Але *AI* не має способу дізнатись, чи палац stale. Він може відповідати на питання використовуючи застарілий контент, не усвідомлюючи це.

### Рішення — Read-Only MCP Tool + Idempotent Writes

**`mempalace_sync_status`** — MCP tool, який AI може викликати для перевірки freshness. Повертає JSON-звіт:

```json
{
  "total_source_files": 145,
  "fresh": 142,
  "stale": 2,
  "missing": 1,
  "no_hash_legacy": 0,
  "status": "stale",
  "message": "2 files changed since last mine. Run the remine_commands to refresh.",
  "stale_files": [
    {"file": "api_client.py", "drawers": 8, "wing": "myproject"}
  ],
  "remine_commands": [
    "mempalace mine /path/to/src --wing myproject --force"
  ]
}
```

**Ключове обмеження:** Цей tool **read-only**. Він звітує про staleness і пропонує shell-команди. Він НЕ майнить і не видаляє нічого. AI передає команди користувачу.

### CLI Sync vs MCP Sync Status

| | `mempalace sync` (CLI, PR #251) | `mempalace_sync_status` (MCP, PR #256) |
|---|---|---|
| **Хто викликає** | Людина в терміналі | AI через MCP протокол |
| **Дія** | Read + Write (видаляє + перемайнює) | Read-only діагностика |
| **Вивід** | Human-readable stdout | JSON для AI |
| **Re-mining** | Виконує атомарно per-file | Пропонує shell-команди |
| **Orphans** | Видаляє якщо `--clean` | Тільки звітує |

Це комплементарні половини: MCP tool — "діагностичний шар" (AI перевіряє freshness), CLI команда — "шар дій" (людина фіксить staleness).

### Freshness Hook (`hooks/mempal_freshness_hook.sh`)

Bash-скрипт, який працює як Claude Code Stop hook:

```
1. Читає stdin для session context (JSON)
2. Якщо stop_hook_active — дозволяє зупинку (запобігає infinite loop)
3. Запускає 'mempalace sync --dry-run' раз за сесію
4. Якщо знайдено stale файли — БЛОКУЄ зупинку AI
   → Повертає reason: "Call mempalace_sync_status to see details"
5. На наступних викликах — дозволяє нормальну зупинку
```

Це як watchdog: AI не може "заснути" поки не перевірить, чи його пам'ять актуальна.

### Статуси freshness

```
Fresh:   md5(file_on_disk.strip()) == drawer.metadata["content_hash"]
Stale:   md5(file_on_disk.strip()) != drawer.metadata["content_hash"]
Missing: файл більше не існує на диску
Legacy:  drawer не має content_hash (замайнений до цієї фічі)
```

### iOS аналогія

MCP sync_status tool — це як `NSFetchedResultsController` delegate, що моніторить зовнішні зміни. Він не модифікує дані, він просто каже: "hey, underlying store changed since you last fetched."

---

# Частина IV: Як PR'и пов'язані між собою

```
PR #239 (Repair)
  └── Фіксить: HNSW corruption що ламає палац
  └── Дозволяє: Безпечне відновлення коли все пішло не так
  └── Статус: Незалежний

PR #243 (Normalizer)
  └── Фіксить: Claude.ai розмови не парсились
  └── Дозволяє: Майнінг Claude.ai chat exports
  └── Статус: Незалежний

PR #251 (Sync Command)
  └── Додає: content_hash до кожного drawer при майнінгу
  └── Додає: CLI команду для детекту та фіксу stale контенту
  └── Залежить від: mining pipeline з miner.py та convo_miner.py
  └── Включає: зміни repair з #239

PR #256 (Sync MCP Tool)
  └── Додає: AI-callable freshness check
  └── Додає: Freshness hook
  └── Залежить від: content_hash з PR #251
  └── Доповнює: CLI sync з PR #251 (діагностика vs дія)
```

**Ланцюг залежностей:** #243 незалежний. #239 незалежний. #251 вводить content_hash. #256 будує на content_hash з #251 для expose freshness до AI.

**Примітка:** PR #251 і #239 розвивались паралельно від спільного предка. Гілка `feat/sync-command` НЕ містить repair-специфічні коміти з `fix/chromadb-hnsw-rebuild` (і навпаки). Обидві гілки мержили upstream/main окремо. Repair-зміни в #251 — це конвергентна еволюція: схожий підхід (read via get(), rebuild fresh), але різні коміти.

---

# Частина V: Критичний аналіз

## 5.1. Сильні сторони

**Метафора палацу працює.** Це не просто красива назва — вона визначає весь API, робить його інтуїтивним для AI-агента і створює ментальну модель для людини-розробника.

**Безпека repair.** Підхід "ніколи не торкай corrupted дані, побудуй новий палац поряд, атомарно заміни" — це інженерно зрілий паттерн. Верифікація перед swap, збереження backup, graceful abort на помилках.

**Content hashing.** Елегантне рішення для incremental sync. MD5 не для безпеки (для цього є `usedforsecurity=False`), а для швидкого порівняння контенту.

**Separation of concerns CLI vs MCP.** CLI (людина) може робити destructive операції. MCP (AI) — тільки read-only діагностика. AI пропонує, людина виконує.

## 5.2. Слабкі сторони та ризики

**Один collection на весь палац.** `mempalace_drawers` — це єдина колекція ChromaDB. При десятках тисяч drawers метадата-фільтрація (WHERE wing="X") працює через повний скан. ChromaDB не має secondary indexes на метаданих. На великих палацах це стане bottleneck.

**MD5 для content_hash.** MD5 має відомі collision attacks. Хоча для порівняння контенту це не security concern (використовується `usedforsecurity=False`), SHA-256 дав би більше впевненості за мінімальну додаткову вартість.

**Відсутність транзакцій при sync.** Delete + re-mine per-file — це не атомарна операція в термінах ChromaDB. Якщо процес впаде між delete і add, drawers для цього файлу будуть втрачені. WAL не використовується для crash recovery.

**AAAK залежність від AI-розуміння.** AAAK працює, тому що Claude/GPT достатньо розумні, щоб розпарсити цей формат. Але немає гарантії, що майбутні моделі будуть так само надійно його інтерпретувати. Це неявний контракт.

**Freshness hook як bash-скрипт.** `mempal_freshness_hook.sh` парсить JSON через Python з bash, що крихко. Якщо Python не в PATH або mempalace не встановлений глобально — hook тихо фейлить.

**Жодного unit test для hooks.** PR #256 не містить тестів для bash-хука. Тестується тільки MCP tool.

## 5.3. Архітектурні спостереження

**Vibe-coded, але архітектурно послідовний.** Незважаючи на те, що код написаний через Claude Code ("навайбкодили"), архітектурні рішення послідовні: метафора палацу наскрізна, separation of concerns чіткий, safety properties repair підтримуються на всіх рівнях.

**Тести є.** PR #243 має 374 рядки тестів. PR #251 має 330 рядків. PR #256 має 184 рядки. Це не "написали і забули" — тести покривають edge cases.

---

# Частина VI: Глосарій

| Термін | Значення |
|--------|---------|
| **ChromaDB** | Open-source векторна база даних. Зберігає текст + ембедінги + метадані. |
| **HNSW** | Hierarchical Navigable Small World — алгоритм приблизного пошуку найближчих сусідів у ChromaDB |
| **MCP** | Model Context Protocol — JSON-RPC 2.0 протокол для AI↔tool комунікації |
| **Embedding** | 384-float вектор, що представляє семантичний зміст текстового чанка |
| **Upsert** | Insert-or-update операція (ідемпотентна) |
| **AAAK** | Lossy стиснення для щоденників: `ENTITIES\|topics\|"quote"\|WEIGHT\|EMOTIONS\|FLAGS` |
| **WAL** | Write-Ahead Log — аудит-трейл всіх операцій запису |
| **Drawer ID** | Детерміністичний SHA-256 hash від `(source_file + chunk_index)`, з префіксом `drawer_{wing}_{room}_` |
| **content_hash** | MD5 stripped content файлу-джерела; спільний для всіх drawers цього файлу; для детекту staleness |
| **CoreML** | Apple ML framework; раніше крашив з ChromaDB's ONNX моделлю на ARM, вирішено оновленням chromadb до 1.5.4+ |
| **all-MiniLM-L6-v2** | Sentence-transformer модель, 384 виміри, працює через ONNX runtime |
| **JSON-RPC 2.0** | Протокол віддаленого виклику процедур поверх JSON (stdin/stdout у випадку MCP) |

---

# Джерела та посилання

**Нейронаука методу локусів:**
- Ondřej et al. (2025). "The method of loci in the context of psychological research: A systematic review and meta-analysis." *British Journal of Psychology*. https://bpspsychub.onlinelibrary.wiley.com/doi/full/10.1111/bjop.12799
- Dresler et al. (2017). "Mnemonic training reshapes brain networks to support superior memory." *Neuron*. https://pmc.ncbi.nlm.nih.gov/articles/PMC7929507/
- bioRxiv (2025). "Method of loci training yields unique prefrontal representations." https://www.biorxiv.org/content/10.1101/2025.02.24.639840v2

**AI пам'ять та векторні бази:**
- IBM (2026). "What Is AI Agent Memory?" https://www.ibm.com/think/topics/ai-agent-memory
- Analytics Vidhya (2026). "Architecture and Orchestration of Memory Systems in AI Agents." https://www.analyticsvidhya.com/blog/2026/04/memory-systems-in-ai-agents/
- freeCodeCamp. "How AI Agents Remember Things: Vector Stores in LLM Memory." https://www.freecodecamp.org/news/how-ai-agents-remember-things-vector-stores-in-llm-memory/

**Репозиторій:**
- https://github.com/MemPalace/mempalace
- PR #239: https://github.com/MemPalace/mempalace/pull/239
- PR #243: https://github.com/MemPalace/mempalace/pull/243
- PR #251: https://github.com/MemPalace/mempalace/pull/251
- PR #256: https://github.com/MemPalace/mempalace/pull/256
