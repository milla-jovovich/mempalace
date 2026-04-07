"""Russian language data for entity detection and AAAK dialect."""

# ==================== Entity Detection ====================

# Person signals — things people do (patterns use {name} placeholder)
PERSON_VERB_PATTERNS = [
    r"\b{name}\s+сказал[аи]?\b",
    r"\b{name}\s+спросил[аи]?\b",
    r"\b{name}\s+ответил[аи]?\b",
    r"\b{name}\s+рассмеялс[яь]\b",
    r"\b{name}\s+почувствовал[аи]?\b",
    r"\b{name}\s+думает\b",
    r"\b{name}\s+хочет\b",
    r"\b{name}\s+любит\b",
    r"\b{name}\s+знает\b",
    r"\b{name}\s+решил[аи]?\b",
    r"\b{name}\s+написал[аи]?\b",
    r"\bпривет\s+{name}\b",
    r"\bспасибо\s+{name}\b",
]

# Project signals — things projects have/do
PROJECT_VERB_PATTERNS = [
    r"\bсобираем\s+{name}\b",
    r"\bсобрал[аи]?\s+{name}\b",
    r"\bзапустил[аи]?\s+{name}\b",
    r"\bвыкатил[аи]?\s+{name}\b",
    r"\bзадеплоил[аи]?\s+{name}\b",
    r"\bустановил[аи]?\s+{name}\b",
    r"\bархитектура\s+{name}\b",
    r"\bсистема\s+{name}\b",
    r"\bрепо\s+{name}\b",
]

# Pronoun patterns for person proximity detection
PRONOUN_PATTERNS = [
    r"\bона\b",
    r"\bей\b",
    r"\bеё\b",
    r"\bон\b",
    r"\bему\b",
    r"\bего\b",
    r"\bони\b",
    r"\bим\b",
    r"\bих\b",
]

# Words that are almost certainly NOT entities (appear capitalized at sentence starts)
ENTITY_STOPWORDS = {
    # Common function words
    "это", "как", "так", "что", "для", "все", "уже", "тоже", "может", "есть",
    "надо", "было", "будет", "были", "если", "потом", "когда", "только", "тут",
    "вот", "ещё", "нет", "даже", "между", "через", "после", "перед", "около",
    "также", "однако", "поэтому", "потому", "поскольку", "впрочем", "кстати",
    # Common nouns (false positive entities at sentence starts)
    "время", "место", "человек", "жизнь", "день", "работа", "система", "мир",
    "вопрос", "случай", "сторона", "дело", "голова", "ребёнок", "слово", "часть",
    "пример", "проблема", "группа", "вариант", "результат", "ответ", "причина",
    "версия", "факт", "идея", "точка", "момент", "задача", "цель", "способ",
    # Abstract/topic words
    "память", "язык", "наука", "история", "будущее", "общество", "культура",
    "технология", "модель", "сеть", "обучение", "процесс", "ошибка", "файл",
}

# ==================== AAAK Dialect ====================

# Keywords that signal emotions in plain text
EMOTION_SIGNALS = {
    "решил": "determ",
    "предпочита": "convict",
    "волну": "anx",
    "радуюсь": "excite",
    "злюсь": "frust",
    "запутал": "confuse",
    "люблю": "love",
    "ненавижу": "rage",
    "надеюсь": "hope",
    "боюсь": "fear",
    "доверяю": "trust",
    "счастлив": "joy",
    "грустно": "grief",
    "удивлён": "surprise",
    "благодар": "grat",
    "интересно": "curious",
    "тревожно": "anx",
    "облегчение": "relief",
    "довольн": "satis",
    "разочаров": "grief",
    "беспокои": "anx",
}

# Keywords that signal flags
FLAG_SIGNALS = {
    "решил": "DECISION",
    "выбрал": "DECISION",
    "перешёл": "DECISION",
    "перешли": "DECISION",
    "заменил": "DECISION",
    "вместо": "DECISION",
    "потому что": "DECISION",
    "основал": "ORIGIN",
    "создал": "ORIGIN",
    "начал": "ORIGIN",
    "запустил": "ORIGIN",
    "первый раз": "ORIGIN",
    "ключевой": "CORE",
    "фундаментальн": "CORE",
    "важнейш": "CORE",
    "принцип": "CORE",
    "убеждение": "CORE",
    "поворотный момент": "PIVOT",
    "всё изменил": "PIVOT",
    "осознал": "PIVOT",
    "прорыв": "PIVOT",
    "озарение": "PIVOT",
    "архитектура": "TECHNICAL",
    "деплой": "TECHNICAL",
    "инфраструктур": "TECHNICAL",
    "алгоритм": "TECHNICAL",
    "фреймворк": "TECHNICAL",
    "сервер": "TECHNICAL",
    "конфиг": "TECHNICAL",
    "база данных": "TECHNICAL",
}

# Stop words for topic extraction
TOPIC_STOPWORDS = {
    "это", "как", "так", "что", "для", "все", "уже", "тоже", "может", "есть",
    "надо", "было", "будет", "были", "если", "потом", "когда", "только", "тут",
    "вот", "ещё", "нет", "даже", "между", "через", "после", "перед", "около",
    "также", "однако", "поэтому", "потому", "поскольку", "впрочем", "кстати",
    "нужно", "можно", "очень", "просто", "более", "менее", "сейчас", "всегда",
    "никогда", "где", "куда", "откуда", "зачем", "почему", "какой", "этот",
    "тот", "такой", "который", "свой", "наш", "ваш", "мой", "твой",
}

# Words that signal important/decision sentences
DECISION_WORDS = {
    "решил", "потому", "вместо", "предпочита", "выбрал", "осознал",
    "важно", "ключев", "критичн", "обнаружил", "узнал", "вывод",
    "решение", "причина", "почему", "прорыв",
}
