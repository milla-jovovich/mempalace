"""
Shared constants for MemPalace.

Centralizes magic numbers that control chunking, retrieval limits,
layer sizing, and similarity thresholds across the codebase.
"""

# ---------------------------------------------------------------------------
# Chunking
# ---------------------------------------------------------------------------
PROJECT_CHUNK_SIZE = 800  # chars per drawer for project files
PROJECT_CHUNK_OVERLAP = 100  # overlap between consecutive chunks
PROJECT_MIN_CHUNK_SIZE = 50  # skip tiny chunks from project files
CONVO_MIN_CHUNK_SIZE = 30  # minimum chars for conversation chunks

# ---------------------------------------------------------------------------
# Layer 1 — Essential Story
# ---------------------------------------------------------------------------
L1_MAX_DRAWERS = 15  # at most 15 moments in wake-up
L1_MAX_CHARS = 3200  # hard cap on total L1 text (~800 tokens)

# ---------------------------------------------------------------------------
# Search & retrieval defaults
# ---------------------------------------------------------------------------
DEFAULT_SEARCH_RESULTS = 5  # default n_results for searches
DEFAULT_L2_RESULTS = 10  # default results for Layer 2 on-demand retrieval
DUPLICATE_THRESHOLD = 0.9  # similarity threshold for duplicate detection
DUPLICATE_CANDIDATES = 5  # how many candidates to check for duplicates

# ---------------------------------------------------------------------------
# Graph traversal
# ---------------------------------------------------------------------------
DEFAULT_MAX_HOPS = 2  # BFS depth for palace graph traversal
GRAPH_BATCH_SIZE = 1000  # batch size when loading room data from ChromaDB
GRAPH_MAX_RESULTS = 50  # cap on traversal / tunnel results

# ---------------------------------------------------------------------------
# Entity detection
# ---------------------------------------------------------------------------
ENTITY_MAX_BYTES_PER_FILE = 5000  # first N bytes scanned per file
ENTITY_DEFAULT_MAX_FILES = 10  # max files to scan for entities

# ---------------------------------------------------------------------------
# Snippet truncation
# ---------------------------------------------------------------------------
L1_SNIPPET_MAX = 200  # max chars for a single L1 snippet
L2_SNIPPET_MAX = 300  # max chars for L2/L3 snippets
DUPLICATE_PREVIEW_MAX = 200  # max chars shown in duplicate preview

# ---------------------------------------------------------------------------
# Diary
# ---------------------------------------------------------------------------
DIARY_DEFAULT_LAST_N = 10  # default diary entries to return

