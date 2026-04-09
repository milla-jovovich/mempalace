use std::collections::HashMap;
use std::fs;
use std::path::{Path, PathBuf};

use serde::{Deserialize, Serialize};

use crate::error::{CoreError, Result};
use crate::paths::{
    default_config_dir, default_palace_path, ensure_private_dir, ensure_private_file_perms,
};

pub const DEFAULT_COLLECTION_NAME: &str = "mempalace_drawers";

pub const DEFAULT_TOPIC_WINGS: &[&str] = &[
    "emotions",
    "consciousness",
    "memory",
    "technical",
    "identity",
    "family",
    "creative",
];

#[must_use]
pub fn default_topic_wings() -> Vec<String> {
    DEFAULT_TOPIC_WINGS
        .iter()
        .map(|s| (*s).to_string())
        .collect()
}

#[must_use]
pub fn default_hall_keywords() -> HashMap<String, Vec<String>> {
    let mut map = HashMap::new();
    map.insert(
        "emotions".to_string(),
        [
            "scared", "afraid", "worried", "happy", "sad", "love", "hate", "feel", "cry", "tears",
        ]
        .into_iter()
        .map(String::from)
        .collect(),
    );
    map.insert(
        "consciousness".to_string(),
        [
            "consciousness",
            "conscious",
            "aware",
            "real",
            "genuine",
            "soul",
            "exist",
            "alive",
        ]
        .into_iter()
        .map(String::from)
        .collect(),
    );
    map.insert(
        "memory".to_string(),
        [
            "memory", "remember", "forget", "recall", "archive", "palace", "store",
        ]
        .into_iter()
        .map(String::from)
        .collect(),
    );
    map.insert(
        "technical".to_string(),
        [
            "code", "python", "script", "bug", "error", "function", "api", "database", "server",
        ]
        .into_iter()
        .map(String::from)
        .collect(),
    );
    map.insert(
        "identity".to_string(),
        ["identity", "name", "who am i", "persona", "self"]
            .into_iter()
            .map(String::from)
            .collect(),
    );
    map.insert(
        "family".to_string(),
        [
            "family", "kids", "children", "daughter", "son", "parent", "mother", "father",
        ]
        .into_iter()
        .map(String::from)
        .collect(),
    );
    map.insert(
        "creative".to_string(),
        [
            "game", "gameplay", "player", "app", "design", "art", "music", "story",
        ]
        .into_iter()
        .map(String::from)
        .collect(),
    );
    map
}

#[derive(Debug, Clone, Default, Serialize, Deserialize)]
pub struct FileConfig {
    #[serde(default)]
    pub palace_path: Option<String>,
    #[serde(default)]
    pub collection_name: Option<String>,
    #[serde(default)]
    pub topic_wings: Option<Vec<String>>,
    #[serde(default)]
    pub hall_keywords: Option<HashMap<String, Vec<String>>>,
    #[serde(default)]
    pub people_map: Option<HashMap<String, String>>,
}

#[derive(Debug, Clone)]
pub struct Config {
    dir: PathBuf,
    file_path: PathBuf,
    people_map_path: PathBuf,
    file: FileConfig,
}

impl Config {
    pub fn load() -> Self {
        Self::with_config_dir(default_config_dir())
    }

    pub fn with_config_dir<P: Into<PathBuf>>(config_dir: P) -> Self {
        let dir = config_dir.into();
        let file_path = dir.join("config.json");
        let people_map_path = dir.join("people_map.json");
        let file = read_file_config(&file_path);

        Self {
            dir,
            file_path,
            people_map_path,
            file,
        }
    }

    #[must_use]
    pub fn config_dir(&self) -> &Path {
        &self.dir
    }

    #[must_use]
    pub fn palace_path(&self) -> String {
        if let Ok(v) = std::env::var("MEMPALACE_PALACE_PATH") {
            return v;
        }
        if let Ok(v) = std::env::var("MEMPAL_PALACE_PATH") {
            return v;
        }
        self.file
            .palace_path
            .clone()
            .unwrap_or_else(|| default_palace_path().to_string_lossy().into_owned())
    }

    #[must_use]
    pub fn collection_name(&self) -> String {
        self.file
            .collection_name
            .clone()
            .unwrap_or_else(|| DEFAULT_COLLECTION_NAME.to_string())
    }

    #[must_use]
    pub fn people_map(&self) -> HashMap<String, String> {
        if self.people_map_path.exists() {
            if let Ok(bytes) = fs::read_to_string(&self.people_map_path) {
                if let Ok(map) = serde_json::from_str::<HashMap<String, String>>(&bytes) {
                    return map;
                }
            }
        }
        self.file.people_map.clone().unwrap_or_default()
    }

    #[must_use]
    pub fn topic_wings(&self) -> Vec<String> {
        self.file
            .topic_wings
            .clone()
            .unwrap_or_else(default_topic_wings)
    }

    #[must_use]
    pub fn hall_keywords(&self) -> HashMap<String, Vec<String>> {
        self.file
            .hall_keywords
            .clone()
            .unwrap_or_else(default_hall_keywords)
    }

    pub fn init(&self) -> Result<PathBuf> {
        ensure_private_dir(&self.dir)?;
        if !self.file_path.exists() {
            let default = FileConfig {
                palace_path: Some(default_palace_path().to_string_lossy().into_owned()),
                collection_name: Some(DEFAULT_COLLECTION_NAME.to_string()),
                topic_wings: Some(default_topic_wings()),
                hall_keywords: Some(default_hall_keywords()),
                people_map: None,
            };
            let body =
                serde_json::to_string_pretty(&default).map_err(|source| CoreError::Json {
                    path: self.file_path.clone(),
                    source,
                })?;
            fs::write(&self.file_path, body).map_err(|source| CoreError::Io {
                path: self.file_path.clone(),
                source,
            })?;
            ensure_private_file_perms(&self.file_path)?;
        }
        Ok(self.file_path.clone())
    }

    pub fn save_people_map(&self, people_map: &HashMap<String, String>) -> Result<PathBuf> {
        ensure_private_dir(&self.dir)?;
        let body = serde_json::to_string_pretty(people_map).map_err(|source| CoreError::Json {
            path: self.people_map_path.clone(),
            source,
        })?;
        fs::write(&self.people_map_path, body).map_err(|source| CoreError::Io {
            path: self.people_map_path.clone(),
            source,
        })?;
        Ok(self.people_map_path.clone())
    }
}

fn read_file_config(path: &Path) -> FileConfig {
    if !path.exists() {
        return FileConfig::default();
    }
    let Ok(body) = fs::read_to_string(path) else {
        return FileConfig::default();
    };
    serde_json::from_str(&body).unwrap_or_default()
}

#[cfg(test)]
mod tests {
    #![allow(clippy::unwrap_used)]

    use std::sync::Mutex;

    use serde_json::json;
    use tempfile::tempdir;

    use super::*;

    static ENV_LOCK: Mutex<()> = Mutex::new(());

    fn clear_env() {
        std::env::remove_var("MEMPALACE_PALACE_PATH");
        std::env::remove_var("MEMPAL_PALACE_PATH");
    }

    #[test]
    fn default_config_exposes_collection_name() {
        let _g = ENV_LOCK.lock().unwrap();
        clear_env();
        let tmp = tempdir().unwrap();
        let cfg = Config::with_config_dir(tmp.path());
        assert!(cfg.palace_path().contains("palace"));
        assert_eq!(cfg.collection_name(), "mempalace_drawers");
    }

    #[test]
    fn config_reads_from_json_file() {
        let _g = ENV_LOCK.lock().unwrap();
        clear_env();
        let tmp = tempdir().unwrap();
        fs::write(
            tmp.path().join("config.json"),
            json!({"palace_path": "/custom/palace"}).to_string(),
        )
        .unwrap();
        let cfg = Config::with_config_dir(tmp.path());
        assert_eq!(cfg.palace_path(), "/custom/palace");
    }

    #[test]
    fn env_var_overrides_file() {
        let _g = ENV_LOCK.lock().unwrap();
        clear_env();
        std::env::set_var("MEMPALACE_PALACE_PATH", "/env/palace");
        let tmp = tempdir().unwrap();
        let cfg = Config::with_config_dir(tmp.path());
        assert_eq!(cfg.palace_path(), "/env/palace");
        clear_env();
    }

    #[test]
    fn legacy_env_var_also_works() {
        let _g = ENV_LOCK.lock().unwrap();
        clear_env();
        std::env::set_var("MEMPAL_PALACE_PATH", "/legacy/path");
        let tmp = tempdir().unwrap();
        let cfg = Config::with_config_dir(tmp.path());
        assert_eq!(cfg.palace_path(), "/legacy/path");
        clear_env();
    }

    #[test]
    fn init_creates_config_json() {
        let _g = ENV_LOCK.lock().unwrap();
        clear_env();
        let tmp = tempdir().unwrap();
        let cfg = Config::with_config_dir(tmp.path());
        let p = cfg.init().unwrap();
        assert!(p.exists());
        let body: serde_json::Value =
            serde_json::from_str(&fs::read_to_string(&p).unwrap()).unwrap();
        assert!(body.get("palace_path").is_some());
    }

    #[test]
    fn init_is_idempotent() {
        let _g = ENV_LOCK.lock().unwrap();
        clear_env();
        let tmp = tempdir().unwrap();
        let cfg = Config::with_config_dir(tmp.path());
        cfg.init().unwrap();
        cfg.init().unwrap();
        let body: serde_json::Value =
            serde_json::from_str(&fs::read_to_string(tmp.path().join("config.json")).unwrap())
                .unwrap();
        assert!(body.get("palace_path").is_some());
    }

    #[test]
    fn bad_json_falls_back_to_defaults() {
        let _g = ENV_LOCK.lock().unwrap();
        clear_env();
        let tmp = tempdir().unwrap();
        fs::write(tmp.path().join("config.json"), "not json").unwrap();
        let cfg = Config::with_config_dir(tmp.path());
        assert!(!cfg.palace_path().is_empty());
    }

    #[test]
    fn people_map_loaded_from_file() {
        let _g = ENV_LOCK.lock().unwrap();
        clear_env();
        let tmp = tempdir().unwrap();
        fs::write(
            tmp.path().join("people_map.json"),
            json!({"bob": "Robert"}).to_string(),
        )
        .unwrap();
        let cfg = Config::with_config_dir(tmp.path());
        assert_eq!(
            cfg.people_map().get("bob").map(String::as_str),
            Some("Robert")
        );
    }

    #[test]
    fn people_map_bad_json_returns_empty() {
        let _g = ENV_LOCK.lock().unwrap();
        clear_env();
        let tmp = tempdir().unwrap();
        fs::write(tmp.path().join("people_map.json"), "bad").unwrap();
        let cfg = Config::with_config_dir(tmp.path());
        assert!(cfg.people_map().is_empty());
    }

    #[test]
    fn people_map_missing_returns_empty() {
        let _g = ENV_LOCK.lock().unwrap();
        clear_env();
        let tmp = tempdir().unwrap();
        let cfg = Config::with_config_dir(tmp.path());
        assert!(cfg.people_map().is_empty());
    }

    #[test]
    fn topic_wings_default_includes_emotions() {
        let _g = ENV_LOCK.lock().unwrap();
        clear_env();
        let tmp = tempdir().unwrap();
        let cfg = Config::with_config_dir(tmp.path());
        let wings = cfg.topic_wings();
        assert!(wings.contains(&"emotions".to_string()));
    }

    #[test]
    fn hall_keywords_default_includes_technical() {
        let _g = ENV_LOCK.lock().unwrap();
        clear_env();
        let tmp = tempdir().unwrap();
        let cfg = Config::with_config_dir(tmp.path());
        assert!(cfg.hall_keywords().contains_key("technical"));
    }

    #[test]
    fn save_people_map_round_trip() {
        let _g = ENV_LOCK.lock().unwrap();
        clear_env();
        let tmp = tempdir().unwrap();
        let cfg = Config::with_config_dir(tmp.path());
        let mut map = HashMap::new();
        map.insert("alice".to_string(), "Alice Smith".to_string());
        let p = cfg.save_people_map(&map).unwrap();
        assert!(p.exists());
        let loaded = cfg.people_map();
        assert_eq!(loaded.get("alice").map(String::as_str), Some("Alice Smith"));
    }

    #[test]
    fn collection_name_from_file() {
        let _g = ENV_LOCK.lock().unwrap();
        clear_env();
        let tmp = tempdir().unwrap();
        fs::write(
            tmp.path().join("config.json"),
            json!({"collection_name": "custom_col"}).to_string(),
        )
        .unwrap();
        let cfg = Config::with_config_dir(tmp.path());
        assert_eq!(cfg.collection_name(), "custom_col");
    }
}
