"""English language data for entity detection and AAAK dialect."""

# ==================== Entity Detection ====================

# Person signals — things people do (patterns use {name} placeholder)
PERSON_VERB_PATTERNS = [
    r"\b{name}\s+said\b",
    r"\b{name}\s+asked\b",
    r"\b{name}\s+told\b",
    r"\b{name}\s+replied\b",
    r"\b{name}\s+laughed\b",
    r"\b{name}\s+smiled\b",
    r"\b{name}\s+cried\b",
    r"\b{name}\s+felt\b",
    r"\b{name}\s+thinks?\b",
    r"\b{name}\s+wants?\b",
    r"\b{name}\s+loves?\b",
    r"\b{name}\s+hates?\b",
    r"\b{name}\s+knows?\b",
    r"\b{name}\s+decided\b",
    r"\b{name}\s+pushed\b",
    r"\b{name}\s+wrote\b",
    r"\bhey\s+{name}\b",
    r"\bthanks?\s+{name}\b",
    r"\bhi\s+{name}\b",
    r"\bdear\s+{name}\b",
]

# Project signals — things projects have/do
PROJECT_VERB_PATTERNS = [
    r"\bbuilding\s+{name}\b",
    r"\bbuilt\s+{name}\b",
    r"\bship(?:ping|ped)?\s+{name}\b",
    r"\blaunch(?:ing|ed)?\s+{name}\b",
    r"\bdeploy(?:ing|ed)?\s+{name}\b",
    r"\binstall(?:ing|ed)?\s+{name}\b",
    r"\bthe\s+{name}\s+architecture\b",
    r"\bthe\s+{name}\s+pipeline\b",
    r"\bthe\s+{name}\s+system\b",
    r"\bthe\s+{name}\s+repo\b",
    r"\b{name}\s+v\d+\b",
    r"\b{name}\.py\b",
    r"\b{name}-core\b",
    r"\b{name}-local\b",
    r"\bimport\s+{name}\b",
    r"\bpip\s+install\s+{name}\b",
]

# Pronoun patterns for person proximity detection
PRONOUN_PATTERNS = [
    r"\bshe\b",
    r"\bher\b",
    r"\bhers\b",
    r"\bhe\b",
    r"\bhim\b",
    r"\bhis\b",
    r"\bthey\b",
    r"\bthem\b",
    r"\btheir\b",
]

# Words that are almost certainly NOT entities
ENTITY_STOPWORDS = {
    "the", "a", "an", "and", "or", "but", "in", "on", "at", "to", "for", "of",
    "with", "by", "from", "as", "is", "was", "are", "were", "be", "been", "being",
    "have", "has", "had", "do", "does", "did", "will", "would", "could", "should",
    "may", "might", "must", "shall", "can", "this", "that", "these", "those",
    "it", "its", "they", "them", "their", "we", "our", "you", "your", "i", "my",
    "me", "he", "she", "his", "her", "who", "what", "when", "where", "why", "how",
    "which", "if", "then", "so", "not", "no", "yes", "ok", "okay", "just", "very",
    "really", "also", "already", "still", "even", "only", "here", "there", "now",
    "then", "too", "up", "out", "about", "like", "use", "get", "got", "make",
    "made", "take", "put", "come", "go", "see", "know", "think", "true", "false",
    "none", "null", "new", "old", "all", "any", "some", "true", "false", "return",
    "print", "def", "class", "import", "from",
    # Common capitalized words in prose that aren't entities
    "step", "usage", "run", "check", "find", "add", "get", "set", "list", "args",
    "dict", "str", "int", "bool", "path", "file", "type", "name", "note", "example",
    "option", "result", "error", "warning", "info", "every", "each", "more", "less",
    "next", "last", "first", "second", "stack", "layer", "mode", "test", "stop",
    "start", "copy", "move", "source", "target", "output", "input", "data", "item",
    "key", "value", "returns", "raises", "yields", "none", "self", "cls", "kwargs",
    # Common sentence-starting / abstract words
    "world", "well", "want", "topic", "choose", "social", "cars", "phones",
    "healthcare", "ex", "machina", "deus", "human", "humans", "people", "things",
    "something", "nothing", "everything", "anything", "someone", "everyone", "anyone",
    "way", "time", "day", "life", "place", "thing", "part", "kind", "sort", "case",
    "point", "idea", "fact", "sense", "question", "answer", "reason", "number",
    "version", "system",
    # Greetings and filler words
    "hey", "hi", "hello", "thanks", "thank", "right", "let", "ok",
    # UI/action words
    "click", "hit", "press", "tap", "drag", "drop", "open", "close", "save", "load",
    "launch", "install", "download", "upload", "scroll", "select", "enter", "submit",
    "cancel", "confirm", "delete", "copy", "paste", "type", "write", "read", "search",
    "find", "show", "hide",
    # Filesystem/technical
    "desktop", "documents", "downloads", "users", "home", "library", "applications",
    "system", "preferences", "settings", "terminal",
    # Abstract/topic words
    "actor", "vector", "remote", "control", "duration", "fetch",
    "agents", "tools", "others", "guards", "ethics", "regulation", "learning",
    "thinking", "memory", "language", "intelligence", "technology", "society",
    "culture", "future", "history", "science", "model", "models", "network",
    "networks", "training", "inference",
}

# ==================== AAAK Dialect ====================

# Keywords that signal emotions in plain text
EMOTION_SIGNALS = {
    "decided": "determ",
    "prefer": "convict",
    "worried": "anx",
    "excited": "excite",
    "frustrated": "frust",
    "confused": "confuse",
    "love": "love",
    "hate": "rage",
    "hope": "hope",
    "fear": "fear",
    "trust": "trust",
    "happy": "joy",
    "sad": "grief",
    "surprised": "surprise",
    "grateful": "grat",
    "curious": "curious",
    "wonder": "wonder",
    "anxious": "anx",
    "relieved": "relief",
    "satisf": "satis",
    "disappoint": "grief",
    "concern": "anx",
}

# Keywords that signal flags
FLAG_SIGNALS = {
    "decided": "DECISION",
    "chose": "DECISION",
    "switched": "DECISION",
    "migrated": "DECISION",
    "replaced": "DECISION",
    "instead of": "DECISION",
    "because": "DECISION",
    "founded": "ORIGIN",
    "created": "ORIGIN",
    "started": "ORIGIN",
    "born": "ORIGIN",
    "launched": "ORIGIN",
    "first time": "ORIGIN",
    "core": "CORE",
    "fundamental": "CORE",
    "essential": "CORE",
    "principle": "CORE",
    "belief": "CORE",
    "always": "CORE",
    "never forget": "CORE",
    "turning point": "PIVOT",
    "changed everything": "PIVOT",
    "realized": "PIVOT",
    "breakthrough": "PIVOT",
    "epiphany": "PIVOT",
    "api": "TECHNICAL",
    "database": "TECHNICAL",
    "architecture": "TECHNICAL",
    "deploy": "TECHNICAL",
    "infrastructure": "TECHNICAL",
    "algorithm": "TECHNICAL",
    "framework": "TECHNICAL",
    "server": "TECHNICAL",
    "config": "TECHNICAL",
}

# Stop words for topic extraction
TOPIC_STOPWORDS = {
    "the", "a", "an", "is", "are", "was", "were", "be", "been", "being",
    "have", "has", "had", "do", "does", "did", "will", "would", "could",
    "should", "may", "might", "shall", "can", "to", "of", "in", "for",
    "on", "with", "at", "by", "from", "as", "into", "about", "between",
    "through", "during", "before", "after", "above", "below", "up", "down",
    "out", "off", "over", "under", "again", "further", "then", "once",
    "here", "there", "when", "where", "why", "how", "all", "each", "every",
    "both", "few", "more", "most", "other", "some", "such", "no", "nor",
    "not", "only", "own", "same", "so", "than", "too", "very", "just",
    "don", "now", "and", "but", "or", "if", "while", "that", "this",
    "these", "those", "it", "its", "i", "we", "you", "he", "she", "they",
    "me", "him", "her", "us", "them", "my", "your", "his", "our", "their",
    "what", "which", "who", "whom", "also", "much", "many", "like",
    "because", "since", "get", "got", "use", "used", "using", "make",
    "made", "thing", "things", "way", "well", "really", "want", "need",
}

# Words that signal important/decision sentences
DECISION_WORDS = {
    "decided", "because", "instead", "prefer", "switched", "chose",
    "realized", "important", "key", "critical", "discovered", "learned",
    "conclusion", "solution", "reason", "why", "breakthrough", "insight",
}
