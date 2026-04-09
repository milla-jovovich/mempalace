//! Keyword-based memory classifier. Port of Python mempalace/general_extractor.py.

use std::collections::{HashMap, HashSet};
use std::sync::LazyLock;

use regex::Regex;

static DECISION_MARKER_STRINGS: &[&str] = &[
    r"\blet'?s (use|go with|try|pick|choose|switch to)\b",
    r"\bwe (should|decided|chose|went with|picked|settled on)\b",
    r"\bi'?m going (to|with)\b",
    r"\bbetter (to|than|approach|option|choice)\b",
    r"\binstead of\b",
    r"\brather than\b",
    r"\bthe reason (is|was|being)\b",
    r"\bbecause\b",
    r"\btrade-?off\b",
    r"\bpros and cons\b",
    r"\bover\b.*\bbecause\b",
    r"\barchitecture\b",
    r"\bapproach\b",
    r"\bstrategy\b",
    r"\bpattern\b",
    r"\bstack\b",
    r"\bframework\b",
    r"\binfrastructure\b",
    r"\bset (it |this )?to\b",
    r"\bconfigure\b",
    r"\bdefault\b",
];

static PREFERENCE_MARKER_STRINGS: &[&str] = &[
    r"\bi prefer\b",
    r"\balways use\b",
    r"\bnever use\b",
    r"\bdon'?t (ever |like to )?(use|do|mock|stub|import)\b",
    r"\bi like (to|when|how)\b",
    r"\bi hate (when|how|it when)\b",
    r"\bplease (always|never|don'?t)\b",
    r"\bmy (rule|preference|style|convention) is\b",
    r"\bwe (always|never)\b",
    r"\bfunctional\b.*\bstyle\b",
    r"\bimperative\b",
    r"\bsnake_?case\b",
    r"\bcamel_?case\b",
    r"\btabs\b.*\bspaces\b",
    r"\bspaces\b.*\btabs\b",
    r"\buse\b.*\binstead of\b",
];

static MILESTONE_MARKER_STRINGS: &[&str] = &[
    r"\bit works\b",
    r"\bit worked\b",
    r"\bgot it working\b",
    r"\bfixed\b",
    r"\bsolved\b",
    r"\bbreakthrough\b",
    r"\bfigured (it )?out\b",
    r"\bnailed it\b",
    r"\bcracked (it|the)\b",
    r"\bfinally\b",
    r"\bfirst time\b",
    r"\bfirst ever\b",
    r"\bnever (done|been|had) before\b",
    r"\bdiscovered\b",
    r"\brealized\b",
    r"\bfound (out|that)\b",
    r"\bturns out\b",
    r"\bthe key (is|was|insight)\b",
    r"\bthe trick (is|was)\b",
    r"\bnow i (understand|see|get it)\b",
    r"\bbuilt\b",
    r"\bcreated\b",
    r"\bimplemented\b",
    r"\bshipped\b",
    r"\blaunched\b",
    r"\bdeployed\b",
    r"\breleased\b",
    r"\bprototype\b",
    r"\bproof of concept\b",
    r"\bdemo\b",
    r"\bversion \d",
    r"\bv\d+\.\d+",
    r"\d+x (compression|faster|slower|better|improvement|reduction)",
    r"\d+% (reduction|improvement|faster|better|smaller)",
];

static PROBLEM_MARKER_STRINGS: &[&str] = &[
    r"\b(bug|error|crash|fail|broke|broken|issue|problem)\b",
    r"\bdoesn'?t work\b",
    r"\bnot working\b",
    r"\bwon'?t\b.*\bwork\b",
    r"\bkeeps? (failing|crashing|breaking|erroring)\b",
    r"\broot cause\b",
    r"\bthe (problem|issue|bug) (is|was)\b",
    r"\bturns out\b.*\b(was|because|due to)\b",
    r"\bthe fix (is|was)\b",
    r"\bworkaround\b",
    r"\bthat'?s why\b",
    r"\bthe reason it\b",
    r"\bfixed (it |the |by )\b",
    r"\bsolution (is|was)\b",
    r"\bresolved\b",
    r"\bpatched\b",
    r"\bthe answer (is|was)\b",
    r"\b(had|need) to\b.*\binstead\b",
];

static EMOTION_MARKER_STRINGS: &[&str] = &[
    r"\blove\b",
    r"\bscared\b",
    r"\bafraid\b",
    r"\bproud\b",
    r"\bhurt\b",
    r"\bhappy\b",
    r"\bsad\b",
    r"\bcry\b",
    r"\bcrying\b",
    r"\bmiss\b",
    r"\bsorry\b",
    r"\bgrateful\b",
    r"\bangry\b",
    r"\bworried\b",
    r"\blonely\b",
    r"\bbeautiful\b",
    r"\bamazing\b",
    r"\bwonderful\b",
    r"i feel",
    r"i'm scared",
    r"i love you",
    r"i'm sorry",
    r"i can't",
    r"i wish",
    r"i miss",
    r"i need",
    r"never told anyone",
    r"nobody knows",
    r"\*[^*]+\*",
];

fn compile_markers(patterns: &[&str]) -> Vec<Regex> {
    patterns.iter().filter_map(|p| Regex::new(p).ok()).collect()
}

pub static ALL_MARKERS: LazyLock<HashMap<&'static str, Vec<Regex>>> = LazyLock::new(|| {
    let mut map = HashMap::new();
    map.insert("decision", compile_markers(DECISION_MARKER_STRINGS));
    map.insert("preference", compile_markers(PREFERENCE_MARKER_STRINGS));
    map.insert("milestone", compile_markers(MILESTONE_MARKER_STRINGS));
    map.insert("problem", compile_markers(PROBLEM_MARKER_STRINGS));
    map.insert("emotional", compile_markers(EMOTION_MARKER_STRINGS));
    map
});

pub static POSITIVE_WORDS: LazyLock<HashSet<&'static str>> = LazyLock::new(|| {
    [
        "pride",
        "proud",
        "joy",
        "happy",
        "love",
        "loving",
        "beautiful",
        "amazing",
        "wonderful",
        "incredible",
        "fantastic",
        "brilliant",
        "perfect",
        "excited",
        "thrilled",
        "grateful",
        "warm",
        "breakthrough",
        "success",
        "works",
        "working",
        "solved",
        "fixed",
        "nailed",
        "heart",
        "hug",
        "precious",
        "adore",
    ]
    .iter()
    .copied()
    .collect()
});

pub static NEGATIVE_WORDS: LazyLock<HashSet<&'static str>> = LazyLock::new(|| {
    [
        "bug",
        "error",
        "crash",
        "crashing",
        "crashed",
        "fail",
        "failed",
        "failing",
        "failure",
        "broken",
        "broke",
        "breaking",
        "breaks",
        "issue",
        "problem",
        "wrong",
        "stuck",
        "blocked",
        "unable",
        "impossible",
        "missing",
        "terrible",
        "horrible",
        "awful",
        "worse",
        "worst",
        "panic",
        "disaster",
        "mess",
    ]
    .iter()
    .copied()
    .collect()
});

#[allow(clippy::expect_used)]
static CODE_LINE_PATTERNS: LazyLock<Vec<Regex>> = LazyLock::new(|| {
    vec![
        Regex::new(r"^\s*[$#]\s").expect("static regex"),
        Regex::new(
            r"^\s*(cd|source|echo|export|pip|npm|git|python|bash|curl|wget|mkdir|rm|cp|mv|ls|cat|grep|find|chmod|sudo|brew|docker)\s",
        )
        .expect("static regex"),
        Regex::new(r"^\s*```").expect("static regex"),
        Regex::new(r"^\s*(import|from|def|class|function|const|let|var|return)\s")
            .expect("static regex"),
        Regex::new(r"^\s*[A-Z_]{2,}=").expect("static regex"),
        Regex::new(r"^\s*\|").expect("static regex"),
        Regex::new(r"^\s*[-]{2,}").expect("static regex"),
        Regex::new(r"^\s*[{}\[\]]\s*$").expect("static regex"),
        Regex::new(r"^\s*(if|for|while|try|except|elif|else:)\b").expect("static regex"),
        Regex::new(r"^\s*\w+\.\w+\(").expect("static regex"),
        Regex::new(r"^\s*\w+ = \w+\.\w+").expect("static regex"),
    ]
});

#[allow(clippy::expect_used)]
static RESOLUTION_PATTERNS: LazyLock<Vec<Regex>> = LazyLock::new(|| {
    vec![
        Regex::new(r"\bfixed\b").expect("static regex"),
        Regex::new(r"\bsolved\b").expect("static regex"),
        Regex::new(r"\bresolved\b").expect("static regex"),
        Regex::new(r"\bpatched\b").expect("static regex"),
        Regex::new(r"\bgot it working\b").expect("static regex"),
        Regex::new(r"\bit works\b").expect("static regex"),
        Regex::new(r"\bnailed it\b").expect("static regex"),
        Regex::new(r"\bfigured (it )?out\b").expect("static regex"),
        Regex::new(r"\bthe (fix|answer|solution)\b").expect("static regex"),
    ]
});

#[allow(clippy::expect_used)]
static TURN_PATTERNS: LazyLock<Vec<Regex>> = LazyLock::new(|| {
    vec![
        Regex::new(r"^>\s").expect("static regex"),
        Regex::new(r"(?i)^(Human|User|Q)\s*:").expect("static regex"),
        Regex::new(r"(?i)^(Assistant|AI|A|Claude|ChatGPT)\s*:").expect("static regex"),
    ]
});

#[derive(Debug, Clone, PartialEq, Eq, Hash)]
pub enum MemoryType {
    Decision,
    Preference,
    Milestone,
    Problem,
    Emotional,
}

#[derive(Debug, Clone)]
pub struct Memory {
    pub content: String,
    pub memory_type: MemoryType,
    pub confidence: f32,
    pub chunk_index: u32,
}

pub(crate) fn score_markers(text: &str, markers: &[Regex]) -> (f32, Vec<String>) {
    let text_lower = text.to_lowercase();
    let mut score = 0.0f32;
    let mut keywords: HashSet<String> = HashSet::new();
    for rx in markers {
        let matches: Vec<_> = rx.find_iter(&text_lower).collect();
        if !matches.is_empty() {
            score += matches.len() as f32;
            for m in &matches {
                keywords.insert(m.as_str().to_owned());
            }
        }
    }
    (score, keywords.into_iter().collect())
}

pub(crate) fn get_sentiment(text: &str) -> &'static str {
    let words: HashSet<String> = text
        .split(|c: char| !c.is_alphanumeric())
        .filter(|w| !w.is_empty())
        .map(|w| w.to_lowercase())
        .collect();
    let pos = words
        .iter()
        .filter(|w| POSITIVE_WORDS.contains(w.as_str()))
        .count();
    let neg = words
        .iter()
        .filter(|w| NEGATIVE_WORDS.contains(w.as_str()))
        .count();
    if pos > neg {
        "positive"
    } else if neg > pos {
        "negative"
    } else {
        "neutral"
    }
}

pub(crate) fn has_resolution(text: &str) -> bool {
    let lower = text.to_lowercase();
    RESOLUTION_PATTERNS.iter().any(|rx| rx.is_match(&lower))
}

pub(crate) fn is_code_line(line: &str) -> bool {
    let stripped = line.trim();
    if stripped.is_empty() {
        return false;
    }
    if CODE_LINE_PATTERNS.iter().any(|rx| rx.is_match(stripped)) {
        return true;
    }
    let alpha_count = stripped.chars().filter(|c| c.is_alphabetic()).count();
    let alpha_ratio = alpha_count as f64 / stripped.len() as f64;
    alpha_ratio < 0.4 && stripped.len() > 10
}

pub(crate) fn extract_prose(text: &str) -> String {
    let mut prose: Vec<&str> = Vec::new();
    let mut in_code = false;
    for line in text.lines() {
        if line.trim().starts_with("```") {
            in_code = !in_code;
            continue;
        }
        if in_code {
            continue;
        }
        if !is_code_line(line) {
            prose.push(line);
        }
    }
    let result = prose.join("\n");
    let result = result.trim();
    if result.is_empty() {
        text.to_owned()
    } else {
        result.to_owned()
    }
}

fn disambiguate(memory_type: &str, text: &str, scores: &HashMap<&str, f32>) -> String {
    let sentiment = get_sentiment(text);

    if memory_type == "problem" && has_resolution(text) {
        if scores.get("emotional").copied().unwrap_or(0.0) > 0.0 && sentiment == "positive" {
            return "emotional".to_owned();
        }
        return "milestone".to_owned();
    }

    if memory_type == "problem" && sentiment == "positive" {
        if scores.get("milestone").copied().unwrap_or(0.0) > 0.0 {
            return "milestone".to_owned();
        }
        if scores.get("emotional").copied().unwrap_or(0.0) > 0.0 {
            return "emotional".to_owned();
        }
    }

    memory_type.to_owned()
}

fn str_to_memory_type(s: &str) -> Option<MemoryType> {
    match s {
        "decision" => Some(MemoryType::Decision),
        "preference" => Some(MemoryType::Preference),
        "milestone" => Some(MemoryType::Milestone),
        "problem" => Some(MemoryType::Problem),
        "emotional" => Some(MemoryType::Emotional),
        _ => None,
    }
}

pub(crate) fn split_into_segments(text: &str) -> Vec<String> {
    let lines: Vec<&str> = text.lines().collect();

    let turn_count = lines
        .iter()
        .filter(|line| {
            let stripped = line.trim();
            TURN_PATTERNS.iter().any(|pat| pat.is_match(stripped))
        })
        .count();

    if turn_count >= 3 {
        return split_by_turns(&lines);
    }

    let paragraphs: Vec<String> = text
        .split("\n\n")
        .map(|p| p.trim().to_owned())
        .filter(|p| !p.is_empty())
        .collect();

    if paragraphs.len() <= 1 && lines.len() > 20 {
        return lines
            .chunks(25)
            .map(|chunk| chunk.join("\n").trim().to_owned())
            .filter(|s| !s.is_empty())
            .collect();
    }

    paragraphs
}

fn split_by_turns(lines: &[&str]) -> Vec<String> {
    let mut segments: Vec<String> = Vec::new();
    let mut current: Vec<&str> = Vec::new();

    for &line in lines {
        let stripped = line.trim();
        let is_turn = TURN_PATTERNS.iter().any(|pat| pat.is_match(stripped));

        if is_turn && !current.is_empty() {
            segments.push(current.join("\n"));
            current = vec![line];
        } else {
            current.push(line);
        }
    }
    if !current.is_empty() {
        segments.push(current.join("\n"));
    }
    segments
}

pub fn extract_memories(text: &str, min_confidence: f32) -> Vec<Memory> {
    let paragraphs = split_into_segments(text);
    let mut memories: Vec<Memory> = Vec::new();

    for para in &paragraphs {
        if para.trim().len() < 20 {
            continue;
        }

        let prose = extract_prose(para);

        let mut scores: HashMap<&str, f32> = HashMap::new();
        for (mem_type, markers) in ALL_MARKERS.iter() {
            let (score, _) = score_markers(&prose, markers.as_slice());
            if score > 0.0 {
                scores.insert(mem_type, score);
            }
        }

        if scores.is_empty() {
            continue;
        }

        let length_bonus: f32 = if para.len() > 500 {
            2.0
        } else if para.len() > 200 {
            1.0
        } else {
            0.0
        };

        let (max_type, max_score) = scores
            .iter()
            .max_by(|a, b| a.1.partial_cmp(b.1).unwrap_or(std::cmp::Ordering::Equal))
            .map(|(k, v)| (*k, *v + length_bonus))
            .unwrap_or(("decision", 0.0 + length_bonus));

        let max_type = disambiguate(max_type, &prose, &scores);

        let confidence = (max_score / 5.0).min(1.0);
        if confidence < min_confidence {
            continue;
        }

        let memory_type = match str_to_memory_type(&max_type) {
            Some(t) => t,
            None => continue,
        };

        memories.push(Memory {
            content: para.trim().to_owned(),
            memory_type,
            confidence,
            chunk_index: memories.len() as u32,
        });
    }

    memories
}

#[cfg(test)]
mod tests {
    #![allow(clippy::unwrap_used)]

    use super::*;

    #[test]
    fn test_extract_memories_empty_text() {
        assert_eq!(extract_memories("", 0.3).len(), 0);
    }

    #[test]
    fn test_extract_memories_no_markers() {
        let result = extract_memories("The quick brown fox jumped over the lazy dog.", 0.3);
        assert!(result.is_empty());
    }

    #[test]
    fn test_extract_memories_short_text_skipped() {
        let result = extract_memories("ok sure", 0.3);
        assert!(result.is_empty());
    }

    #[test]
    fn test_extract_memories_decision() {
        let text = "We decided to go with PostgreSQL instead of MySQL \
                    because the performance was better for our use case. \
                    The trade-off was more complexity in setup.";
        let result = extract_memories(text, 0.3);
        assert!(!result.is_empty());
        assert!(result.iter().any(|m| m.memory_type == MemoryType::Decision));
    }

    #[test]
    fn test_extract_memories_preference() {
        let text = "I prefer using snake_case in Python code. \
                    Please always use type hints. \
                    Never use wildcard imports.";
        let result = extract_memories(text, 0.3);
        assert!(!result.is_empty());
        assert!(result
            .iter()
            .any(|m| m.memory_type == MemoryType::Preference));
    }

    #[test]
    fn test_extract_memories_milestone() {
        let text = "It finally works! After three days of debugging, \
                    I figured out the issue. The breakthrough was realizing \
                    the config file was cached. Got it working at 2am.";
        let result = extract_memories(text, 0.3);
        assert!(!result.is_empty());
        assert!(result
            .iter()
            .any(|m| m.memory_type == MemoryType::Milestone));
    }

    #[test]
    fn test_extract_memories_problem() {
        let text = "There's a critical bug in the auth module. \
                    The error keeps crashing the server. \
                    The root cause was a missing null check. \
                    The problem is that tokens expire silently.";
        let result = extract_memories(text, 0.3);
        assert!(!result.is_empty());
        let types: HashSet<_> = result.iter().map(|m| &m.memory_type).collect();
        assert!(types.contains(&MemoryType::Problem) || types.contains(&MemoryType::Milestone));
    }

    #[test]
    fn test_extract_memories_emotional() {
        let text = "I feel so proud of what we built together. \
                    I love working on this project, it makes me happy. \
                    I'm grateful for the team and the beautiful code we wrote.";
        let result = extract_memories(text, 0.3);
        assert!(!result.is_empty());
        assert!(result
            .iter()
            .any(|m| m.memory_type == MemoryType::Emotional));
    }

    #[test]
    fn test_extract_memories_chunk_index_increments() {
        let text = "We decided to use React because it fits our team.\n\n\
                    I prefer functional components always.\n\n\
                    It works! We finally shipped the v1.0 release.";
        let result = extract_memories(text, 0.3);
        if result.len() >= 2 {
            let indices: Vec<u32> = result.iter().map(|m| m.chunk_index).collect();
            assert_eq!(indices, (0..result.len() as u32).collect::<Vec<_>>());
        }
    }

    #[test]
    fn test_score_markers_with_matches() {
        let markers = ALL_MARKERS.get("decision").unwrap();
        let (score, keywords) = score_markers(
            "we decided to go with postgres because it is faster",
            markers.as_slice(),
        );
        assert!(score > 0.0);
        assert!(!keywords.is_empty());
    }

    #[test]
    fn test_score_markers_no_matches() {
        let markers = ALL_MARKERS.get("decision").unwrap();
        let (score, keywords) = score_markers("nothing relevant here", markers.as_slice());
        assert_eq!(score, 0.0);
        assert!(keywords.is_empty());
    }

    #[test]
    fn test_get_sentiment_positive() {
        assert_eq!(
            get_sentiment("I am so happy and proud of this breakthrough"),
            "positive"
        );
    }

    #[test]
    fn test_get_sentiment_negative() {
        assert_eq!(
            get_sentiment("This bug caused a crash and total failure"),
            "negative"
        );
    }

    #[test]
    fn test_get_sentiment_neutral() {
        assert_eq!(get_sentiment("The meeting is at three"), "neutral");
    }

    #[test]
    fn test_has_resolution_true() {
        assert!(has_resolution("I fixed the auth bug and it works now"));
    }

    #[test]
    fn test_has_resolution_false() {
        assert!(!has_resolution("The server keeps crashing"));
    }

    #[test]
    fn test_is_code_line_detects_code() {
        assert!(is_code_line("  import os"));
        assert!(is_code_line("  $ pip install flask"));
        assert!(is_code_line("  ```python"));
    }

    #[test]
    fn test_is_code_line_allows_prose() {
        assert!(!is_code_line("This is a regular sentence about coding."));
        assert!(!is_code_line(""));
    }

    #[test]
    fn test_extract_prose_strips_code_blocks() {
        let text = "Hello world\n```\nimport os\nprint('hi')\n```\nGoodbye";
        let result = extract_prose(text);
        assert!(!result.contains("import os"));
        assert!(result.contains("Hello world"));
        assert!(result.contains("Goodbye"));
    }

    #[test]
    fn test_extract_prose_returns_original_if_all_code() {
        let text = "import os\nfrom sys import argv";
        let result = extract_prose(text);
        assert!(!result.is_empty());
    }

    #[test]
    fn test_split_into_segments_by_paragraph() {
        let text = "First paragraph.\n\nSecond paragraph.\n\nThird paragraph.";
        let result = split_into_segments(text);
        assert_eq!(result.len(), 3);
    }

    #[test]
    fn test_split_into_segments_by_turns() {
        let mut lines = Vec::new();
        for i in 0..5 {
            lines.push(format!("Human: Question {i}"));
            lines.push(format!("Assistant: Answer {i}"));
        }
        let text = lines.join("\n");
        let result = split_into_segments(&text);
        assert!(result.len() >= 3);
    }

    #[test]
    fn test_split_into_segments_single_block() {
        let lines: Vec<String> = (0..30)
            .map(|i| format!("Line {i} of the document"))
            .collect();
        let text = lines.join("\n");
        let result = split_into_segments(&text);
        assert!(!result.is_empty());
    }

    #[test]
    fn test_all_markers_has_five_types() {
        assert_eq!(ALL_MARKERS.len(), 5);
        assert!(ALL_MARKERS.contains_key("decision"));
        assert!(ALL_MARKERS.contains_key("preference"));
        assert!(ALL_MARKERS.contains_key("milestone"));
        assert!(ALL_MARKERS.contains_key("problem"));
        assert!(ALL_MARKERS.contains_key("emotional"));
    }

    #[test]
    fn test_positive_words() {
        assert!(POSITIVE_WORDS.contains("happy"));
        assert!(POSITIVE_WORDS.contains("proud"));
    }

    #[test]
    fn test_negative_words() {
        assert!(NEGATIVE_WORDS.contains("bug"));
        assert!(NEGATIVE_WORDS.contains("crash"));
    }
}
