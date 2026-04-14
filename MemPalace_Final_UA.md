# MemPalace: Палац Пам'яті для AI-Агентів

## Повний технічний розбір архітектури, Pull Requests та науки запам'ятовування

**Автор:** Ruslan Popescu | **Дата:** Квітень 2026
**Репозиторій:** github.com/MemPalace/mempalace
**Для кого:** iOS-розробник, який хоче зрозуміти Python/ChromaDB систему на 100%

---

# Розділ 1: Метод Локусів — Чому палаци пам'яті працюють

## 1.1. Історія: від Симоніда до чемпіонатів пам'яті

Близько 500 року до н.е. грецький поет Симонід із Кеосу був на бенкеті, коли покинув залу за хвилини до обвалу даху. Він зміг ідентифікувати загиблих — тому що пам'ятав, де хто сидів. Це вважається моментом народження **методу локусів** (Method of Loci) — мнемонічної техніки, яку систематизував Аристотель у трактаті *De Memoria et Reminiscentia*, і яку масово використовували римські оратори.

Суть методу: уяви знайому будівлю — дім, школу, офіс — і мислено «розмісти» інформацію в конкретних кімнатах. Щоб згадати — мислено «пройди» будівлею, і кожна кімната поверне те, що ти в ній «залишив».

Цицерон описував цю техніку в *De Oratore*. У Середньовіччі монахи використовували палаци пам'яті для запам'ятовування теологічних текстів. У XVI столітті італійський місіонер Маттео Річчі адаптував метод для вивчення китайських ієрогліфів. Джордано Бруно у 1582 році поєднав метод локусів із герметичною філософією у *De umbris idearum*. У XX столітті Френсіс Йейтс повернула академічний інтерес знаковою роботою *The Art of Memory* (1966).

Сьогодні метод локусів — основний інструмент чемпіонів пам'яті: Домінік О'Брайєн (8-разовий чемпіон світу), Джошуа Фоер (*Moonwalking with Einstein*) запам'ятовують перетасовані колоди карт за хвилини завдяки «палацам».

## 1.2. Когнітивна наука: три механізми

Мета-аналіз 2025 року (Ondřej et al., *British Journal of Psychology*) показав **великий ефект** (d = 0.88) методу локусів на негайне серійне пригадування порівняно з простим повторенням. Нейровізуалізаційні дослідження (bioRxiv, лютий 2025) виявили, що тренування методом локусів створює **унікальні нейронні патерни** в префронтальній корі, нижній скроневій та задній тім'яній ділянках.

Метод працює завдяки трьом когнітивним механізмам:

**1. Просторове кодування (Spatial Encoding)**

Гіпокамп — структура мозку, що відповідає за навігацію (place cells, grid cells) — активується і при просторовій навігації, і при епізодичному запам'ятовуванні. Метод локусів «підключає» запам'ятовування до потужної просторової системи мозку. Нобелівська премія 2014 (О'Кіф, Мозер) саме за відкриття цих клітин.

**2. Подвійне кодування (Dual Coding)**

Інформація кодується одночасно вербально (текст) і візуально (образ у кімнаті). За теорією подвійного кодування Аллана Пайвіо, два незалежних канали дають більше «шляхів» для пригадування. Якщо один канал фейлить, другий все ще працює.

**3. Зниження проактивної інтерференції**

Коли раніше вивчений матеріал заважає пригадати новий — це проактивна інтерференція. Просторова прив'язка створює унікальний контекст для кожного фрагменту інформації, тому вони не «злипаються» в пам'яті. Мета-аналіз 2025 підтвердив: MoL значно зменшує ефект інтерференції.

## 1.3. Чому це працює для AI: від людської пам'яті до векторних баз

Дослідники AI-пам'яті категоризують пам'ять агентів так само, як психологи категоризують людську:

**Людська пам'ять → AI аналог:**

- **Сенсорна (мілісекунди)** → Поточний промпт / контекстне вікно
- **Короткострокова / Робоча (секунди-хвилини)** → Контекстне вікно LLM (200K токенів у Claude)
- **Довгострокова епізодична (роки)** → Векторна база даних з конкретними фрагментами розмов/подій
- **Довгострокова семантична (факти)** → Граф знань (Knowledge Graph) з сутностями та зв'язками
- **Процедурна (навички)** → Системні промпти, інструкції, протоколи

MemPalace реалізує всі три типи довгострокової пам'яті:

1. **Епізодична** — ChromaDB drawers з фрагментами розмов та файлів (коли? де? що говорили?)
2. **Семантична** — SQLite Knowledge Graph з темпоральними трійками (хто? що робить? з коли?)
3. **Процедурна** — AAAK-інструкції та Protocol Injection через MCP

### Чому саме векторний пошук?

Коли ти шукаєш в Core Data, ти пишеш предикат: `NSPredicate(format: "name == %@", "Alice")`. Це **точний пошук** — або є збіг, або ні. Якщо ти шукаєш «помилка в авторизації», він не знайде текст «authentication error in the login flow».

Векторний пошук працює інакше. Текст "Як працюють актори в Swift?" і "Swift concurrency actors async/await" не мають жодного спільного слова (крім "Swift"), але семантично вони близькі. Модель `all-MiniLM-L6-v2` перетворює обидва тексти в 384-мірні вектори, і ці вектори будуть близькими в просторі. ChromaDB знаходить цю близькість за допомогою HNSW-індексу.

Це як людська асоціативна пам'ять: ти не згадуєш речі за точним ключовим словом, а за *змістом* — "щось було про архітектуру акторів... щось таке..."

## 1.4. Палац як метафора та архітектура

| Класичний концепт | Реалізація в коді | Структура даних |
|---|---|---|
| **Палац** | Директорія ChromaDB на диску | `~/.mempalace/palace/` |
| **Крило** (Wing) | Проєкт або домен | Метадане `wing` на кожному drawer |
| **Кімната** (Room) | Тема всередині крила | Метадане `room` на кожному drawer |
| **Шухляда** (Drawer) | Один фрагмент запам'ятованого контенту | Документ ChromaDB: текст + ембедінг + метадані |
| **Зал** (Hall) | Тип зв'язку між кімнатами | Мітка ребра в графі |
| **Тунель** (Tunnel) | Кімната з однаковою назвою в різних крилах | Обчислюється динамічно |
| **Граф знань** | Фактичні зв'язки (хто/що/коли) | SQLite з сутностями та темпоральними трійками |

Метафора палацу — це не просто красива назва. Вона визначає всю архітектуру API: ти не «записуєш дані» — ти «кладеш в шухляду кімнати крила палацу». Це робить MCP-протокол інтуїтивним для AI-агента, бо він може мислити просторово. Wings/rooms створюють природну таксономію — AI може обмежити пошук конкретним wing'ом, як `NSPredicate(format: "wing == %@", projectName)`.

---

# Розділ 2: Архітектура — Як влаштований MemPalace

## 2.1. Карта модулів (для iOS-розробника)

| Модуль Python | iOS аналог | Що робить |
|---|---|---|
| `palace.py` | `CoreDataStack` | Доступ до ChromaDB, `get_collection()`, `file_already_mined()` |
| `mcp_server.py` | `URLSession` + API Router | JSON-RPC 2.0 сервер з 24 інструментами |
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

## 2.2. Data Flow: від файлу до AI-відповіді

```
ФАЙЛ НА ДИСКУ
    ↓
[miner.py / convo_miner.py]
    ↓ read_text() + strip()
ПОВНИЙ ТЕКСТ
    ↓ file_content_hash() → MD5
CONTENT_HASH (зберігається в метаданих кожного drawer)
    ↓ chunk_text() → ~800 символів, overlap 100
ЧАНКИ (список текстових фрагментів)
    ↓ add_drawer() → ChromaDB.add()
    ↓ all-MiniLM-L6-v2 (ONNX) → 384-float вектор
CHROMADB: текст + embedding + metadata (wing, room, source_file, content_hash)
    ↓
[mcp_server.py] — JSON-RPC 2.0, stdin/stdout
    ↓ mempalace_search(query)
    ↓ query → embedding → HNSW approximate nearest neighbor
РЕЗУЛЬТАТИ: top-K drawers з similarity scores
    ↓
AI-АГЕНТ (Claude Code) — використовує як контекст для відповіді
```

## 2.3. ChromaDB — Векторне сховище

ChromaDB — це як Core Data, де замість предикатів у тебе семантична близькість.

- **Collection** = Entity/Table. MemPalace використовує одну: `mempalace_drawers`.
- **Document** = Текстовий контент шухляди (чанк файлу або обмін у розмові).
- **Embedding** = 384-float вектор від моделі `all-MiniLM-L6-v2` (ONNX). Два тексти зі схожим змістом дають вектори, близькі в 384-вимірному просторі.
- **Metadata** = Key-value пари: `wing`, `room`, `source_file`, `content_hash`, `filed_at`. Для фільтрації, НЕ для пошуку.
- **HNSW Index** = Hierarchical Navigable Small World — індекс приблизного пошуку найближчих сусідів. Багатошаровий граф, де вузли — вектори, ребра з'єднують близькі вектори. Верхні шари — мало вузлів для швидкої маршрутизації, нижні — всі вузли для точності.

### Проблема HNSW (чому існує PR #239)

Коли ти робиш `upsert` для документа, який вже існує, C++ бібліотека `hnswlib` викликає `updatePoint`. На macOS ARM (Apple Silicon) це може викликати segfault. Крім того, повторні upsert'и без дедуплікації роздувають `link_lists.bin` (файл HNSW-індексу) — він росте необмежено.

**Критичний інсайт:** SQLite файл (`chroma.sqlite3`) НЕ пошкоджується. Документи та метадані зберігаються окремо від векторного індексу. Метод `get()` читає з SQLite, обходячи HNSW повністю. Це — escape hatch для repair.

## 2.4. MCP-протокол — Як AI спілкується з палацом

MCP Server (`mcp_server.py`) — JSON-RPC 2.0 сервер, написаний вручну (без SDK).

**Транспорт:** Читає JSON зі stdin, пише JSON у stdout. Запускається як subprocess Claude Code.

**24 інструменти** зареєстровані в словнику `TOOLS`:

- **Читання:** `mempalace_status`, `mempalace_search`, `mempalace_list_wings`, `mempalace_list_rooms`, `mempalace_get_taxonomy`, `mempalace_check_duplicate`, `mempalace_get_aaak_spec`, `mempalace_get_drawer`, `mempalace_list_drawers`, `mempalace_sync_status`
- **Запис:** `mempalace_add_drawer`, `mempalace_update_drawer`, `mempalace_delete_drawer`, `mempalace_diary_write`, `mempalace_diary_read`, `mempalace_memories_filed_away`
- **Граф знань:** `mempalace_kg_add`, `mempalace_kg_query`, `mempalace_kg_invalidate`, `mempalace_kg_timeline`, `mempalace_kg_stats`
- **Граф палацу:** `mempalace_traverse`, `mempalace_find_tunnels`, `mempalace_graph_stats`
- **Конфігурація:** `mempalace_hook_settings`

**Write-Ahead Log (WAL):** Кожна операція запису логується в `~/.mempalace/wal/write_log.jsonl` *перед* виконанням — аудит-трейл, не crash recovery.

**Protocol Injection:** Перший виклик `mempalace_status` повертає `PALACE_PROTOCOL` і `AAAK_SPEC` прямо у відповіді — AI навчається використовувати палац без системного промпту.

## 2.5. 4-рівнева архітектура пам'яті

MemPalace реалізує 4-рівневу систему, натхненну моделлю когнітивного навантаження (Cognitive Load Theory, Sweller 1988):

```
Layer 0: Identity       (~100 токенів)   — Завжди завантажено. "Хто я?"
Layer 1: Essential Story (~500-800)      — Завжди завантажено. Ключові моменти.
Layer 2: On-Demand      (~200-500 кожен) — Завантажується за потреби.
Layer 3: Deep Search    (необмежено)     — Повний семантичний пошук ChromaDB.
```

Вартість пробудження: ~600-900 токенів (L0+L1). Залишає 95%+ контексту вільним. Це як iOS-додаток: ти не завантажуєш всю базу в пам'ять — лише те, що потрібно для поточного View.

## 2.6. Pipeline Майнінгу

### Для файлів проєкту (`mempalace mine <dir>`):

```
1. Обхід дерева директорій (пропускає .git, node_modules, __pycache__ тощо)
2. Для кожного файлу:
   a. Перевірити чи вже замайнено (content_hash) → пропустити якщо свіжий
   b. Видалити існуючі drawers для цього файлу (уникає HNSW segfault)
   c. Прочитати вміст файлу
   d. file_content_hash(filepath) → MD5 stripped content
   e. detect_room() → шлях директорії → ім'я файлу → keyword scoring
   f. chunk_text() → ~800 символів з overlap 100
   g. add_drawer(collection, wing, room, content, content_hash)
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
5. detect_convo_room() → technical/architecture/planning/decisions
6. add_drawer() з ingest_mode="convos"
```

### Чанкінг = керовані контекстні вікна

AI-агенти мають обмежений контекст. Зберігати цілі файли непрактично. Чанкінг (~800 символів з 100-символьним overlap'ом) дає AI рівно стільки контексту, скільки потрібно для відповіді — і залишає місце для інших drawer'ів. Це як `UITableView` з `cellForRowAt`: не завантажуєш все, а лише те, що видно.

## 2.7. AAAK Діалект — Lossy стиснення для щоденника

AAAK — кастомний lossy-формат стиснення. Він НЕ МОЖЕ відновити оригінальний текст. Як JPEG для зображень: втрата деталей, але збереження суті.

**Формат:**

```
Header:  FILE_NUM|PRIMARY_ENTITY|DATE|TITLE
Zettel:  ZID:ENTITIES|topic_keywords|"key_quote"|WEIGHT|EMOTIONS|FLAGS
Tunnel:  T:ZID<->ZID|label
Arc:     ARC:emotion->emotion->emotion
```

**Приклад:**

```
Z1:ALC,JOR|swift,concurrency,actors|"вирішили використовувати async/await"|8|determ,conf|DECISION,TECHNICAL
```

**Коди емоцій:** vul=вразливість, joy=радість, fear=страх, trust=довіра, grief=горе, wonder=подив, rage=лють, love=любов, hope=надія, despair=відчай, peace=спокій, humor=гумор

**Прапорці:** ORIGIN, CORE, SENSITIVE, PIVOT, GENESIS, DECISION, TECHNICAL

AAAK дозволяє вмістити більше «пам'яті» в обмежений контекст AI-агента. AI навчається формату через `AAAK_SPEC`, що інжектується у відповідь `mempalace_status`.

## 2.8. Граф Знань (Knowledge Graph)

SQLite база для темпоральних entity-relationship трійок:

```python
kg = KnowledgeGraph()
kg.add_triple("Макс", "дитина_від", "Аліса", valid_from="2015-04-01")
kg.add_triple("Макс", "займається", "плаванням", valid_from="2025-01-01")

# Запит: що було вірним про Макса в січні 2026?
kg.query_entity("Макс", as_of="2026-01-15")

# Інвалідація: факт більше не вірний
kg.invalidate("Макс", "has_issue", "sports_injury", ended="2026-02-15")
```

`invalidate()` встановлює `valid_to`, робить факт історичним. Це як Core Data store з NSDate-атрибутами `validFrom` і `validTo` на кожному зв'язку, що дозволяє запитувати стан світу «на дату X».

Конкурує з Zep (Neo4j в хмарі, $25/місяць+). MemPalace — SQLite локально (безкоштовно).

---

# Розділ 3: PR #239 — Безпечний Repair (HNSW Index Corruption)

**Гілка:** `fix/chromadb-hnsw-rebuild` | **Файли:** `mempalace/cli.py` (+101 / -26)

## 3.1. Проблема

ChromaDB зберігає HNSW-індекс у файлі `link_lists.bin`. При повторних upsert'ах (нормальна операція при re-mining) hnswlib (C++) не дедуплікує — додає нові записи вузлів. Файл росте безконтрольно. Врешті C++-рівень видає segfault.

**Критично:** навіть `delete_collection()` призводить до segfault, бо операція видалення завантажує HNSW-сегменти для знищення. «Очевидний» фікс — видалити і створити колекцію заново — сам крашить процес.

## 3.2. Старий код, що падав

```python
# BEFORE — segfault на корумпованому HNSW
client = chromadb.PersistentClient(palace_path)
client.delete_collection("mempalace_drawers")   # SEGFAULT ТУТ
client.create_collection("mempalace_drawers")
```

## 3.3. Фікс: 6-крокова процедура ремонту

**Крок 1 — Прочитати дані через `get()`, обхід HNSW:**

```python
client = chromadb.PersistentClient(path=palace_path)
col = client.get_collection("mempalace_drawers")
# get() читає з SQLite, НЕ з HNSW
batch = col.get(limit=500, offset=offset, include=["documents", "metadatas"])
```

Батчі по 500 замість старих 5000 — щоб уникнути OOM на великих палацах.

**Крок 2 — Звільнити файлові дескриптори:**

```python
del col
del client
gc.collect()
```

Явне видалення примушує ChromaDB flush'нути і звільнити всі SQLite/HNSW file handles.

**Крок 3 — Побудувати новий палац у тимчасовій директорії:**

```python
rebuild_path = palace_path + "_rebuild"
new_client = chromadb.PersistentClient(path=rebuild_path)
new_col = new_client.create_collection("mempalace_drawers")
```

Оригінальний палац повністю НЕ ТОРКАЄТЬСЯ.

**Крок 4 — Записати дані в новий палац:**

```python
new_col.add(documents=batch_docs, ids=batch_ids, metadatas=batch_metas)
```

Батчі по 100. Якщо запис впав — `sys.exit(1)`, оригінал непошкоджений.

**Крок 5 — Верифікація:**

```python
rebuilt_count = new_col.count()
if rebuilt_count != len(all_ids):
    # Abort — оригінал непошкоджений, partial rebuild збережено
    return
```

**Крок 6 — Атомарна заміна директорій:**

```python
os.rename(palace_path, backup_path)    # оригінал → .backup
os.rename(rebuild_path, palace_path)   # _rebuild → palace
```

`os.rename` на одній файловій системі — атомна операція на рівні ОС. У жоден момент палац не «зникає». Backup зберігається, поки користувач сам не видалить.

## 3.4. Властивості безпеки

- Оригінальний палац ніколи не мутується під час rebuild
- Верифікація перед swap — невідповідність кількості перериває операцію
- Backup зберігається — стара директорія перейменована, не видалена
- Ніякого контакту з HNSW на corrupted індексі — тільки `get()` (SQLite)
- Захист від trailing slash — `palace_path.rstrip(os.sep)`

## 3.5. iOS-аналогія

Уяви, що Core Data SQLite store має corrupt WAL-файл, через який `NSPersistentStoreCoordinator` крашить при будь-якому записі. Фікс: відкрити SQLite напряму через `sqlite3` (обійшовши Core Data), витягти всі рядки, створити fresh store, вставити рядки, атомно поміняти `.sqlite`-файли.

---

# Розділ 4: PR #243 — Фікс нормалайзера Claude.ai

**Гілка:** `fix/claude-ai-chat-normalizer` | **Файли:** `mempalace/normalize.py` (+39/-11), `tests/test_normalize.py` (+374)

## 4.1. Проблема: різні назви полів

MemPalace вміє імпортувати розмови з різних AI-платформ. Модуль `normalize.py` авто-детектить формат і конвертує в канонічний transcript. Claude.ai Privacy Export використовує інші назви полів:

| Поле | Claude Code / ChatGPT | Claude.ai Privacy Export |
|------|----------------------|--------------------------|
| Роль відправника | `"role"` | `"sender"` |
| Значення ролі | `"user"` / `"assistant"` | `"human"` / `"assistant"` |
| Тіло повідомлення | `"content"` (рядок або список блоків) | `"text"` (завжди plain string) |

Старий код перевіряв тільки `role` та `content`. Коли Claude.ai export приходив з `sender: "human"` і `text: "..."` — жоден парсер не спрацьовував. Файл проходив через raw JSON fallback → зберігався як непарсений JSON-blob → пошук по Claude.ai розмовах ефективно не працював.

## 4.2. Фікс: три цільові зміни

**1. Подвійне витягування ролі:**

```python
# BEFORE
role = item.get("role", "")

# AFTER
role = item.get("sender") or item.get("role") or ""
```

**2. Подвійне витягування тексту з null-safety:**

```python
# BEFORE
text = _extract_content(item.get("content", ""))

# AFTER — text перший (Claude.ai), потім content як fallback
text = (item.get("text") or "").strip() or _extract_content(item.get("content", ""))
```

**3. Ізоляція транскриптів по розмовах:**

```python
# BEFORE — всі розмови зливались в один плоский transcript
all_messages = []
for convo in data:
    for item in convo["chat_messages"]:
        all_messages.append(...)

# AFTER — кожна розмова окремо з header'ом
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

**Нюанс:** якщо формат визначений як Claude.ai але всі розмови порожні — повертається `""` замість `None`. Це запобігає fallthrough до Slack-парсера (найбільш permissive).

## 4.3. Ланцюг парсерів

| # | Парсер | Як розпізнає |
|---|--------|-------------|
| 1 | `_try_claude_code_jsonl` | JSONL з type: human/assistant |
| 2 | `_try_codex_jsonl` | JSONL з session_meta guard |
| 3 | `_try_claude_ai_json` **← ЦЕЙ ФІКС** | Масив розмов з sender/role полями |
| 4 | `_try_chatgpt_json` | Mapping tree з author.role |
| 5 | `_try_slack_json` | Масив message-об'єктів (найменш специфічний) |

Це як послідовність `init?(from decoder:)` у Swift, де кожен ініціалізатор пробує інший набір `CodingKeys`.

## 4.4. 7 тестів (+374 рядки)

Покриває: розпізнавання sender-поля, пріоритет text над content, розділення мульти-розмов, плоский формат, зворотна сумісність зі старим role/content, пусті повідомлення, fallback на content blocks.

---

# Розділ 5: PR #251 — Команда Sync (Інкрементальний Re-Mining)

**Гілка:** `feat/sync-command` | **Файли:** 11 файлів, +1323 / -110

**Це — основний PR. Найбільший за обсягом.**

## 5.1. Проблема: застарілий контент

Після першого майнінгу файли змінюються. Палац стає stale — drawers містять застарілий контент. Єдиний варіант — перемайнити все заново (`--force`), що повільно на великих палацах.

## 5.2. Рішення: content hash + incremental sync

Кожен drawer тепер зберігає `content_hash` — MD5-хеш stripped content файлу-джерела:

```python
def file_content_hash(filepath: Path) -> str:
    content = filepath.read_text(encoding="utf-8", errors="replace").strip()
    return hashlib.md5(content.encode(), usedforsecurity=False).hexdigest()
```

- **Вхід:** повний текст файлу, без leading/trailing whitespace
- **Вихід:** 32-символьний hex MD5 digest
- **Всі чанки одного файлу мають один hash** — це file-level властивість
- Для розмов: hash на raw content *до* normalize() — завжди відповідає диску

## 5.3. Повний flow команди `mempalace sync`

**Крок 1 — Сканування палацу:** ітерація drawers батчами по 500, збір унікальних `source_file` з `content_hash`, drawer IDs, wing, ingest_mode.

**Крок 2 — Фільтр по директорії:** якщо `--dir` задано, `Path.resolve()` для коректного порівняння (macOS `/var` → `/private/var` symlink).

**Крок 3 — Класифікація кожного файлу:**

| Стан | Умова | Дія |
|------|-------|-----|
| **Fresh** | Файл існує, hash збігається | Нічого — контент актуальний |
| **Stale** | Файл існує, hash не збігається | Видалити старі drawers + re-mine |
| **Missing** | Файл більше не існує на диску | Повідомити; видалити якщо `--clean` |
| **No-hash** | Drawer без `content_hash` (legacy) | Повідомити; запропонувати `--force` |

**Крок 4 — Звіт:**

```
  Fresh (unchanged):     142
  Stale (changed):       3
  Missing (deleted):     1
  No hash (legacy):      28 (re-mine with --force to add hashes)
```

**Крок 5 — Атомарний per-file re-mining:** для кожного stale файлу: (1) видалити всі drawer IDs, (2) негайно перемайнити, (3) маршрутизація за `ingest_mode`: `"convos"` → conversation miner, інакше → project miner. Контент файлу відсутній у палаці максимум на час обробки одного файлу.

**Крок 6 — Очистка сиріт:** якщо `--clean` — видаляє drawers для відсутніх файлів.

## 5.4. Зміна add() vs upsert()

```python
# BEFORE
collection.upsert(documents=[content], ids=[drawer_id], metadatas=[metadata])

# AFTER
collection.add(documents=[content], ids=[drawer_id], metadatas=[meta])
```

Принципова зміна. `upsert()` = "вставити або оновити" — торкає HNSW для існуючих записів, ризик segfault. `add()` = "вставити, помилка якщо вже існує" — оскільки перед re-mine ми видаляємо старі drawers, дублікати неможливі.

## 5.5. CLI-флаги

| Флаг | Ефект |
|------|-------|
| `--dir <path>` | Синхронізувати тільки файли в цій директорії |
| `--clean` | Видалити drawers для файлів, що більше не існують |
| `--dry-run` | Показати, що зміниться, без модифікації палацу |
| `--force` (на mine) | Видалити ВСІ існуючі drawers перед майнінгом |

## 5.6. Змінені файли

| Файл | Що змінилося |
|------|-------------|
| `cli.py` | `cmd_sync()` (~200 рядків), `_force_clean()`, sync argparse, `--force` на mine |
| `miner.py` | `file_content_hash()`, `content_hash` в `add_drawer()`, pre-mine delete |
| `convo_miner.py` | `filepath_filter`, зберігає `ingest_mode` та `content_hash` |
| `palace.py` | `check_mtime` параметр у `file_already_mined()` |
| `instructions/sync.md` | AI-інструкція для sync |
| `.claude-plugin/commands/sync.md` | Claude Code `/sync` slash command |
| `tests/test_sync.py` | 8 тестів: hash storage, stale detection, missing, legacy |

## 5.7. iOS-аналогія

`NSPersistentHistoryTracking` у Core Data — відстежування що змінилось з останнього sync. Але замість окремих attribute changes — file-level content hashes. Якщо hash відрізняється — весь файл перепроцесовується (всі його Core Data об'єкти видаляються і створюються заново).

---

# Розділ 6: PR #256 — MCP Tool Sync Status + Freshness Hook

**Гілка:** `feat/sync-mcp-tool` | **Файли:** 3 файли, +427

## 6.1. Проблема: AI не знає, що палац застарів

PR #251 дає *людині* команду sync. Але *AI-агент* не має способу дізнатись, чи палац stale. Він може відповідати на запити використовуючи застарілий контент drawer'ів.

## 6.2. Рішення: read-only MCP tool

**`mempalace_sync_status`** — MCP tool для перевірки свіжості. Повертає JSON:

```json
{
  "total_source_files": 145,
  "fresh": 142,
  "stale": 2,
  "missing": 1,
  "status": "stale",
  "message": "2 files changed since last mine",
  "stale_files": [
    {"file": "api_client.py", "drawers": 8, "wing": "myproject"}
  ],
  "remine_commands": [
    "mempalace mine /path/to/src --wing myproject --force"
  ]
}
```

**Ключове:** tool тільки **читає і повідомляє**. Не майнить, не видаляє. AI показує запропоновані shell-команди користувачу.

## 6.3. CLI Sync vs MCP Sync Status

| Аспект | `mempalace sync` (CLI, PR #251) | `mempalace_sync_status` (MCP, PR #256) |
|---|---|---|
| Хто викликає | Людина в терміналі | AI через MCP |
| Дія | Read + Write (видаляє + re-mine) | Read-only діагностика |
| Вивід | Human-readable stdout | JSON для AI |
| Re-mining | Виконує атомно per-file | Пропонує shell-команди |
| Orphans | Видаляє з `--clean` | Тільки повідомляє |

Комплементарні половини: MCP tool — «діагностичний шар», CLI — «action-шар».

## 6.4. Ідемпотентний tool_add_drawer

До цього PR виклик `tool_add_drawer` двічі з тим самим контентом створював два drawer'и. Тепер:

1. **Детерміністичний ID:** якщо `source_file` не задано — `"mcp:" + md5(content)`. Drawer ID: `drawer_{wing}_{room}_{sha256(source+"0")[:24]}`.
2. **Pre-check:** `col.get(ids=[drawer_id])` — якщо вже існує, повертає `{"success": true, "reason": "already_exists"}`.
3. **Семантична перевірка:** `tool_check_duplicate(content, threshold=0.9)` — відхиляє контент зі схожістю >90%.
4. **Спільна маршрутизація:** через `miner.add_drawer()` для консистентних метаданих.

Це критично, бо AI-агенти не мають ідеального контролю потоку — можуть викликати tool двічі через перезапуск або компресію контексту.

## 6.5. Freshness Hook

Bash-скрипт `hooks/mempal_freshness_hook.sh` — Claude Code Stop hook:

1. Читає stdin для session context (JSON)
2. Якщо `stop_hook_active` — дозволяє зупинку (запобігає infinite loop)
3. Запускає `mempalace sync --dry-run` раз за сесію
4. Якщо stale файли — БЛОКУЄ зупинку AI → reason: "Call mempalace_sync_status"
5. На наступних викликах — дозволяє нормальну зупинку

**PreCompact Hook** (головний): спрацьовує перед компресією контексту Claude Code. Каже AI: «Збережи все в MemPalace ЗАРАЗ, поки контекст не втрачено.»

---

# Розділ 7: Як 4 PR'и пов'язані між собою

## 7.1. Ланцюг залежностей

| PR | Залежність | Що вносить |
|---|---|---|
| #239 (Repair) | Незалежний | Безпечний ремонт corrupt HNSW |
| #243 (Normalizer) | Незалежний | Підтримка Claude.ai chat exports |
| #251 (Sync) | Незалежний (нова функціональність) | `content_hash` + CLI sync |
| #256 (Sync MCP) | Залежить від #251 (`content_hash`) | AI-доступ до freshness + idempotent writes |

**Примітка:** PR #251 і #239 розвивались паралельно від спільного предка. Гілка `feat/sync-command` НЕ містить repair-специфічні коміти з `fix/chromadb-hnsw-rebuild` (і навпаки). Repair-зміни в #251 — конвергентна еволюція: схожий підхід (read via get(), rebuild fresh), але різні коміти.

## 7.2. Повний життєвий цикл даних

```
mine → store (з content_hash) → search → detect staleness → sync → repair if corrupt

#243: mine розмов Claude.ai ──────────────────────────────────┐
#251: content_hash при mine ─── sync detects stale ─── re-mine │
#256: AI перевіряє freshness ─── proposes shell commands ──────┤
#239: якщо HNSW corrupt ─── safe rebuild ──────────────────────┘
```

---

# Розділ 8: Чому ця архітектура добре працює для AI-пам'яті

## 8.1. Семантичний пошук замість ключових слів

Традиційний пошук (grep, Spotlight, `NSPredicate`) знаходить точні збіги слів. Якщо шукаєш «помилка в авторизації», він не знайде «authentication error in the login flow». Embedding'и обох текстів будуть «близько» в 384-вимірному просторі — ChromaDB знайде зв'язок, навіть якщо слова різні.

## 8.2. Content hashing = довіра до даних

Завдяки `content_hash` (PR #251) та `sync_status` (PR #256), AI-агент може верифікувати актуальність даних. Це критично для прийняття рішень на основі пам'яті — AI знає, чи можна довіряти drawer'у, чи потрібно порадити людині оновити палац.

## 8.3. Diagnostics-first паттерн

`sync_status` повідомляє, а не діє. Безпечніший паттерн для AI-агентів: діагностуй → запропонуй → людина підтверджує. Менше ризик деструктивної операції.

## 8.4. Ідемпотентність = безпека при повторних запитах

Ідемпотентний `tool_add_drawer` означає, що AI може «пам'ятати» щось кілька разів без дублікатів. AI-агенти не мають ідеального контролю потоку — можуть викликати tool двічі через перезапуск або компресію контексту.

## 8.5. AAAK = більше пам'яті в обмеженому контексті

Lossy-стиснення дозволяє вмістити більше «пам'яті» у обмежений контекст. Замість повного тексту — компактний рядок з сутностями, ключовими словами, цитатою, вагою, емоціями і прапорцями.

---

# Розділ 9: Критичний аналіз

## 9.1. Сильні сторони

**Метафора палацу працює.** Не просто красива назва — визначає весь API, робить його інтуїтивним для AI-агента і створює ментальну модель для людини-розробника.

**Безпека repair.** Підхід «ніколи не торкай corrupted дані, побудуй новий палац поряд, атомарно заміни» — інженерно зрілий паттерн. Верифікація перед swap, backup, graceful abort.

**Separation of concerns CLI vs MCP.** CLI (людина) може робити destructive операції. MCP (AI) — тільки read-only діагностика. AI пропонує, людина виконує.

**Тести.** PR #243 — 374 рядки тестів. PR #251 — 330 рядків. PR #256 — 184 рядки. Edge cases покриті.

## 9.2. Слабкі сторони та ризики

**Один collection на весь палац.** `mempalace_drawers` — єдина колекція ChromaDB. Метадата-фільтрація (`WHERE wing="X"`) — повний скан, не index lookup. На 100K+ drawers це стане bottleneck.

**MD5 для content_hash.** MD5 має відомі collision attacks. Для порівняння контенту це не security concern (`usedforsecurity=False`), але SHA-256 дав би більше впевненості за мінімальну вартість.

**Відсутність транзакцій при sync.** Delete + re-mine per-file — не атомарна операція. Якщо процес впаде між delete і add, drawers для файлу будуть втрачені. WAL не використовується для crash recovery.

**AAAK залежність від AI-розуміння.** Працює, бо Claude/GPT розумні. Немає гарантії для майбутніх моделей. Неявний контракт.

**Freshness hook як bash-скрипт.** Парсить JSON через Python з bash — крихко. Якщо Python не в PATH — тихо фейлить. Жодних тестів для хука.

---

# Розділ 10: Глосарій

| Термін | Значення |
|--------|---------|
| **ChromaDB** | Open-source векторна БД. Текст + embedding + metadata. |
| **HNSW** | Hierarchical Navigable Small World — алгоритм ANN-пошуку |
| **MCP** | Model Context Protocol — JSON-RPC 2.0 для AI↔tool комунікації |
| **Embedding** | 384-float вектор семантичного змісту тексту |
| **Upsert** | Insert-or-update (ідемпотентна операція) |
| **AAAK** | Lossy стиснення: `ENTITIES\|topics\|"quote"\|WEIGHT\|EMOTIONS\|FLAGS` |
| **WAL** | Write-Ahead Log — аудит-трейл операцій запису |
| **Drawer ID** | SHA-256 від `(source_file + chunk_index)`, префікс `drawer_{wing}_{room}_` |
| **content_hash** | MD5 stripped content файлу; спільний для всіх drawers файлу |
| **all-MiniLM-L6-v2** | Sentence-transformer модель, 384 виміри, ONNX runtime |
| **JSON-RPC 2.0** | Протокол RPC поверх JSON (stdin/stdout для MCP) |

---

# Джерела

**Нейронаука методу локусів:**
- Ondřej et al. (2025). "The method of loci in the context of psychological research: A systematic review and meta-analysis." *British Journal of Psychology*. https://bpspsychub.onlinelibrary.wiley.com/doi/full/10.1111/bjop.12799
- Dresler et al. (2017). "Durable memories and efficient neural coding through mnemonic training using the method of loci." *Neuron*. https://pmc.ncbi.nlm.nih.gov/articles/PMC7929507/
- bioRxiv (2025). "Method of loci training yields unique prefrontal representations." https://www.biorxiv.org/content/10.1101/2025.02.24.639840v2
- Wandag (2025). "Neuroscience of Memory Palaces: A Randomized Controlled Trial." https://papers.ssrn.com/sol3/papers.cfm?abstract_id=5292190

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
