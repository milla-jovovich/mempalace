use std::path::PathBuf;

use thiserror::Error;

#[derive(Debug, Error)]
pub enum CoreError {
    #[error("I/O error at {path}: {source}")]
    Io {
        path: PathBuf,
        #[source]
        source: std::io::Error,
    },

    #[error("JSON parse error at {path}: {source}")]
    Json {
        path: PathBuf,
        #[source]
        source: serde_json::Error,
    },

    #[error(transparent)]
    Validation(#[from] ValidationError),
}

#[derive(Debug, Error, PartialEq, Eq)]
pub enum ValidationError {
    #[error("{field} must be a non-empty string")]
    Empty { field: String },

    #[error("{field} exceeds maximum length of {max} characters")]
    TooLong { field: String, max: usize },

    #[error("{field} contains invalid path characters")]
    PathTraversal { field: String },

    #[error("{field} contains null bytes")]
    NullByte { field: String },

    #[error("{field} contains invalid characters")]
    InvalidChars { field: String },

    #[error("content must be a non-empty string")]
    EmptyContent,

    #[error("content exceeds maximum length of {max} characters")]
    ContentTooLong { max: usize },

    #[error("content contains null bytes")]
    ContentNullByte,
}

pub type Result<T> = std::result::Result<T, CoreError>;
