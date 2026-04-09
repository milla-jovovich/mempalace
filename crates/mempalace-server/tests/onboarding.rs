#![allow(clippy::unwrap_used, clippy::expect_used)]

use mempalace_server::onboarding::{
    person_keywords, wing_name_from_person, wing_name_from_project, WingConfig, WingEntry,
};
use tempfile::TempDir;

#[test]
fn wing_name_from_person_slugs_name() {
    assert_eq!(wing_name_from_person("Alice").unwrap(), "wing_alice");
    assert_eq!(
        wing_name_from_person("Kai Rivers").unwrap(),
        "wing_kai_rivers"
    );
    assert_eq!(
        wing_name_from_person("Max O'Neill").unwrap(),
        "wing_max_o_neill"
    );
}

#[test]
fn wing_name_from_project_works() {
    assert_eq!(
        wing_name_from_project("Driftwood").unwrap(),
        "wing_driftwood"
    );
    assert_eq!(wing_name_from_project("my-app").unwrap(), "wing_my_app");
}

#[test]
fn wing_name_empty_is_error() {
    assert!(wing_name_from_person("").is_err());
    assert!(wing_name_from_person("   ").is_err());
    assert!(wing_name_from_person("!!!").is_err());
}

#[test]
fn person_keywords_include_possessive() {
    let kws = person_keywords("Alice");
    assert!(kws.contains(&"alice".to_string()));
    assert!(kws.contains(&"alice's".to_string()));
}

#[test]
fn add_person_populates_wing() {
    let mut cfg = WingConfig::new_empty();
    let name = cfg.add_person("Alice").unwrap();
    assert_eq!(name, "wing_alice");
    let entry = cfg.wings.get("wing_alice").unwrap();
    assert_eq!(entry.wing_type, "person");
    assert!(entry.keywords.contains(&"alice".to_string()));
}

#[test]
fn add_project_populates_wing_with_keywords() {
    let mut cfg = WingConfig::new_empty();
    cfg.add_project("Driftwood", &["analytics", "saas"])
        .unwrap();
    let entry = cfg.wings.get("wing_driftwood").unwrap();
    assert_eq!(entry.wing_type, "project");
    assert!(entry.keywords.contains(&"driftwood".to_string()));
    assert!(entry.keywords.contains(&"analytics".to_string()));
    assert!(entry.keywords.contains(&"saas".to_string()));
}

#[test]
fn save_and_load_roundtrip() {
    let tmp = TempDir::new().unwrap();
    let path = tmp.path().join("wing_config.json");
    let mut cfg = WingConfig::new_empty();
    cfg.add_person("Alice").unwrap();
    cfg.add_project("Driftwood", &["analytics"]).unwrap();
    cfg.save(&path).unwrap();

    let loaded = WingConfig::load(&path).unwrap();
    assert_eq!(loaded, cfg);
}

#[test]
fn default_config_has_default_wing() {
    let cfg = WingConfig::new_empty();
    assert_eq!(cfg.default_wing, "wing_general");
    assert!(cfg.wings.is_empty());
}

#[test]
fn wing_entry_serializes_with_type_key() {
    let entry = WingEntry {
        wing_type: "person".to_string(),
        keywords: vec!["alice".to_string()],
    };
    let json = serde_json::to_string(&entry).unwrap();
    assert!(json.contains("\"type\":\"person\""));
}
