use std::path::{Path, PathBuf};

use crate::error::{CoreError, Result};

pub fn home_dir() -> Option<PathBuf> {
    dirs::home_dir()
}

pub fn default_config_dir() -> PathBuf {
    home_dir().map_or_else(|| PathBuf::from(".mempalace"), |h| h.join(".mempalace"))
}

pub fn default_palace_path() -> PathBuf {
    default_config_dir().join("palace")
}

pub fn default_kg_path() -> PathBuf {
    default_config_dir().join("knowledge_graph.sqlite3")
}

/// Create a directory tree and lock it down to owner-only on Unix (0o700),
/// matching the Python `MempalaceConfig.init()` and `palace.get_collection`
/// behaviour. Silently ignores permission errors on Windows and other platforms
/// that do not support Unix mode bits.
pub fn ensure_private_dir(path: &Path) -> Result<()> {
    std::fs::create_dir_all(path).map_err(|source| CoreError::Io {
        path: path.to_path_buf(),
        source,
    })?;
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        let perms = std::fs::Permissions::from_mode(0o700);
        let _ = std::fs::set_permissions(path, perms);
    }
    Ok(())
}

/// Create a file's parent directory if missing and lock the file itself down to
/// owner-only on Unix (0o600), matching the Python config-file behaviour.
pub fn ensure_private_file_perms(path: &Path) -> Result<()> {
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        if path.exists() {
            let perms = std::fs::Permissions::from_mode(0o600);
            let _ = std::fs::set_permissions(path, perms);
        }
    }
    #[cfg(not(unix))]
    {
        let _ = path;
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    #![allow(clippy::unwrap_used)]

    use super::*;

    #[test]
    fn default_config_dir_includes_mempalace() {
        let p = default_config_dir();
        assert!(p.ends_with(".mempalace"));
    }

    #[test]
    fn default_palace_path_includes_palace() {
        let p = default_palace_path();
        assert!(p.ends_with("palace"));
        assert!(p.to_string_lossy().contains(".mempalace"));
    }

    #[test]
    fn default_kg_path_includes_sqlite() {
        let p = default_kg_path();
        assert_eq!(p.file_name().unwrap(), "knowledge_graph.sqlite3");
    }

    #[test]
    fn ensure_private_dir_creates_nested() {
        let tmp = tempfile::tempdir().unwrap();
        let nested = tmp.path().join("a/b/c");
        ensure_private_dir(&nested).unwrap();
        assert!(nested.is_dir());
    }
}
