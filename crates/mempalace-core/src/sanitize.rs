use std::sync::LazyLock;

use regex::Regex;

use crate::error::ValidationError;

pub const MAX_NAME_LENGTH: usize = 128;
pub const DEFAULT_MAX_CONTENT_LENGTH: usize = 100_000;

static SAFE_NAME_RE: LazyLock<Regex> = LazyLock::new(|| {
    Regex::new(r"^[a-zA-Z0-9][a-zA-Z0-9_ .'-]{0,126}[a-zA-Z0-9]?$")
        .unwrap_or_else(|_| unreachable!("safe name regex is a compile-time constant"))
});

pub fn sanitize_name(value: &str, field_name: &str) -> Result<String, ValidationError> {
    if value.trim().is_empty() {
        return Err(ValidationError::Empty {
            field: field_name.to_string(),
        });
    }

    let trimmed = value.trim();

    if trimmed.chars().count() > MAX_NAME_LENGTH {
        return Err(ValidationError::TooLong {
            field: field_name.to_string(),
            max: MAX_NAME_LENGTH,
        });
    }

    if trimmed.contains("..") || trimmed.contains('/') || trimmed.contains('\\') {
        return Err(ValidationError::PathTraversal {
            field: field_name.to_string(),
        });
    }

    if trimmed.contains('\0') {
        return Err(ValidationError::NullByte {
            field: field_name.to_string(),
        });
    }

    if !SAFE_NAME_RE.is_match(trimmed) {
        return Err(ValidationError::InvalidChars {
            field: field_name.to_string(),
        });
    }

    Ok(trimmed.to_string())
}

pub fn sanitize_content(value: &str, max_length: usize) -> Result<String, ValidationError> {
    if value.trim().is_empty() {
        return Err(ValidationError::EmptyContent);
    }
    if value.chars().count() > max_length {
        return Err(ValidationError::ContentTooLong { max: max_length });
    }
    if value.contains('\0') {
        return Err(ValidationError::ContentNullByte);
    }
    Ok(value.to_string())
}

#[cfg(test)]
mod tests {
    #![allow(clippy::unwrap_used)]

    use super::*;

    #[test]
    fn accepts_simple_name() {
        assert_eq!(sanitize_name("wing_kai", "wing").unwrap(), "wing_kai");
    }

    #[test]
    fn trims_whitespace() {
        assert_eq!(sanitize_name("  wing_kai  ", "wing").unwrap(), "wing_kai");
    }

    #[test]
    fn rejects_empty() {
        assert!(matches!(
            sanitize_name("", "wing"),
            Err(ValidationError::Empty { .. })
        ));
        assert!(matches!(
            sanitize_name("   ", "wing"),
            Err(ValidationError::Empty { .. })
        ));
    }

    #[test]
    fn rejects_path_traversal() {
        assert!(matches!(
            sanitize_name("../etc/passwd", "wing"),
            Err(ValidationError::PathTraversal { .. })
        ));
        assert!(matches!(
            sanitize_name("wing/evil", "wing"),
            Err(ValidationError::PathTraversal { .. })
        ));
        assert!(matches!(
            sanitize_name("wing\\evil", "wing"),
            Err(ValidationError::PathTraversal { .. })
        ));
    }

    #[test]
    fn rejects_null_bytes() {
        assert!(matches!(
            sanitize_name("wing\0bad", "wing"),
            Err(ValidationError::NullByte { .. })
        ));
    }

    #[test]
    fn rejects_too_long_name() {
        let long = "a".repeat(200);
        assert!(matches!(
            sanitize_name(&long, "wing"),
            Err(ValidationError::TooLong { .. })
        ));
    }

    #[test]
    fn rejects_invalid_chars() {
        assert!(matches!(
            sanitize_name("wing$bad", "wing"),
            Err(ValidationError::InvalidChars { .. })
        ));
    }

    #[test]
    fn allows_apostrophes_and_dots() {
        assert!(sanitize_name("O'Brien", "name").is_ok());
        assert!(sanitize_name("file.name", "name").is_ok());
        assert!(sanitize_name("my-project", "name").is_ok());
    }

    #[test]
    fn content_accepts_normal() {
        assert_eq!(sanitize_content("hello world", 100).unwrap(), "hello world");
    }

    #[test]
    fn content_rejects_empty() {
        assert!(matches!(
            sanitize_content("", 100),
            Err(ValidationError::EmptyContent)
        ));
    }

    #[test]
    fn content_rejects_too_long() {
        let big = "a".repeat(200);
        assert!(matches!(
            sanitize_content(&big, 100),
            Err(ValidationError::ContentTooLong { .. })
        ));
    }

    #[test]
    fn content_rejects_null_bytes() {
        assert!(matches!(
            sanitize_content("hello\0world", 100),
            Err(ValidationError::ContentNullByte)
        ));
    }
}
