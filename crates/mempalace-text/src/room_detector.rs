//! Folder-to-room detector. Port of Python mempalace/room_detector_local.py.

use std::collections::HashMap;
use std::io::{BufRead, Write};
use std::path::{Path, PathBuf};
use std::sync::LazyLock;

use serde::Serialize;
use thiserror::Error;

#[derive(Debug, Error)]
pub enum ModuleError {
    #[error("IO error: {0}")]
    Io(#[from] std::io::Error),
    #[error("YAML serialization error: {0}")]
    Yaml(#[from] serde_yml::Error),
    #[error("Directory not found: {0}")]
    NotFound(PathBuf),
}

pub static FOLDER_ROOM_MAP: LazyLock<HashMap<&'static str, &'static str>> = LazyLock::new(|| {
    [
        ("frontend", "frontend"),
        ("front-end", "frontend"),
        ("front_end", "frontend"),
        ("client", "frontend"),
        ("ui", "frontend"),
        ("views", "frontend"),
        ("components", "frontend"),
        ("pages", "frontend"),
        ("backend", "backend"),
        ("back-end", "backend"),
        ("back_end", "backend"),
        ("server", "backend"),
        ("api", "backend"),
        ("routes", "backend"),
        ("services", "backend"),
        ("controllers", "backend"),
        ("models", "backend"),
        ("database", "backend"),
        ("db", "backend"),
        ("docs", "documentation"),
        ("doc", "documentation"),
        ("documentation", "documentation"),
        ("wiki", "documentation"),
        ("readme", "documentation"),
        ("notes", "documentation"),
        ("design", "design"),
        ("designs", "design"),
        ("mockups", "design"),
        ("wireframes", "design"),
        ("assets", "design"),
        ("storyboard", "design"),
        ("costs", "costs"),
        ("cost", "costs"),
        ("budget", "costs"),
        ("finance", "costs"),
        ("financial", "costs"),
        ("pricing", "costs"),
        ("invoices", "costs"),
        ("accounting", "costs"),
        ("meetings", "meetings"),
        ("meeting", "meetings"),
        ("calls", "meetings"),
        ("meeting_notes", "meetings"),
        ("standup", "meetings"),
        ("minutes", "meetings"),
        ("team", "team"),
        ("staff", "team"),
        ("hr", "team"),
        ("hiring", "team"),
        ("employees", "team"),
        ("people", "team"),
        ("research", "research"),
        ("references", "research"),
        ("reading", "research"),
        ("papers", "research"),
        ("planning", "planning"),
        ("roadmap", "planning"),
        ("strategy", "planning"),
        ("specs", "planning"),
        ("requirements", "planning"),
        ("tests", "testing"),
        ("test", "testing"),
        ("testing", "testing"),
        ("qa", "testing"),
        ("scripts", "scripts"),
        ("tools", "scripts"),
        ("utils", "scripts"),
        ("config", "configuration"),
        ("configs", "configuration"),
        ("settings", "configuration"),
        ("infrastructure", "configuration"),
        ("infra", "configuration"),
        ("deploy", "configuration"),
    ]
    .iter()
    .copied()
    .collect()
});

static SKIP_DIRS: LazyLock<std::collections::HashSet<&'static str>> = LazyLock::new(|| {
    [
        ".git",
        "node_modules",
        "__pycache__",
        ".venv",
        "venv",
        "env",
        "dist",
        "build",
        ".next",
        "coverage",
    ]
    .iter()
    .copied()
    .collect()
});

#[derive(Debug, Clone)]
pub struct Room {
    pub name: String,
    pub description: String,
    pub keywords: Vec<String>,
}

pub fn detect_rooms_from_folders(project_dir: &Path) -> Vec<Room> {
    let mut found_rooms: HashMap<String, String> = HashMap::new();

    let top_entries = match std::fs::read_dir(project_dir) {
        Ok(e) => e,
        Err(_) => return vec![general_room()],
    };

    for entry in top_entries.flatten() {
        let path = entry.path();
        if !path.is_dir() {
            continue;
        }
        let dir_name = match path.file_name().and_then(|n| n.to_str()) {
            Some(n) => n.to_owned(),
            None => continue,
        };
        if SKIP_DIRS.contains(dir_name.as_str()) {
            continue;
        }
        let name_lower = dir_name.to_lowercase().replace('-', "_");
        if let Some(&room_name) = FOLDER_ROOM_MAP.get(name_lower.as_str()) {
            found_rooms
                .entry(room_name.to_owned())
                .or_insert(dir_name.clone());
        } else if dir_name.len() > 2 && dir_name.starts_with(|c: char| c.is_alphabetic()) {
            let clean = dir_name.to_lowercase().replace('-', "_").replace(' ', "_");
            found_rooms.entry(clean).or_insert(dir_name.clone());
        }
    }

    let second_level_entries = match std::fs::read_dir(project_dir) {
        Ok(e) => e,
        Err(_) => return build_room_list(found_rooms),
    };

    for entry in second_level_entries.flatten() {
        let path = entry.path();
        if !path.is_dir() {
            continue;
        }
        let parent_name = match path.file_name().and_then(|n| n.to_str()) {
            Some(n) => n.to_owned(),
            None => continue,
        };
        if SKIP_DIRS.contains(parent_name.as_str()) {
            continue;
        }
        let sub_entries = match std::fs::read_dir(&path) {
            Ok(e) => e,
            Err(_) => continue,
        };
        for sub_entry in sub_entries.flatten() {
            let sub_path = sub_entry.path();
            if !sub_path.is_dir() {
                continue;
            }
            let sub_name = match sub_path.file_name().and_then(|n| n.to_str()) {
                Some(n) => n.to_owned(),
                None => continue,
            };
            if SKIP_DIRS.contains(sub_name.as_str()) {
                continue;
            }
            let name_lower = sub_name.to_lowercase().replace('-', "_");
            if let Some(&room_name) = FOLDER_ROOM_MAP.get(name_lower.as_str()) {
                found_rooms
                    .entry(room_name.to_owned())
                    .or_insert(sub_name.clone());
            }
        }
    }

    build_room_list(found_rooms)
}

fn build_room_list(found: HashMap<String, String>) -> Vec<Room> {
    let mut rooms: Vec<Room> = found
        .into_iter()
        .map(|(room_name, original)| Room {
            description: format!("Files from {original}/"),
            keywords: vec![room_name.clone(), original.to_lowercase()],
            name: room_name,
        })
        .collect();

    if !rooms.iter().any(|r| r.name == "general") {
        rooms.push(general_room());
    }
    rooms
}

fn general_room() -> Room {
    Room {
        name: "general".to_owned(),
        description: "Files that don't fit other rooms".to_owned(),
        keywords: vec![],
    }
}

pub fn detect_rooms_from_files(project_dir: &Path) -> Vec<Room> {
    let mut keyword_counts: HashMap<String, u32> = HashMap::new();

    let skip: std::collections::HashSet<&str> = [
        ".git",
        "node_modules",
        "__pycache__",
        ".venv",
        "venv",
        "dist",
        "build",
    ]
    .iter()
    .copied()
    .collect();

    walk_and_count(project_dir, &skip, &mut keyword_counts);

    let mut sorted: Vec<(String, u32)> = keyword_counts.into_iter().collect();
    sorted.sort_by(|a, b| b.1.cmp(&a.1));

    let mut rooms: Vec<Room> = Vec::new();
    for (room, count) in sorted {
        if count < 2 {
            continue;
        }
        rooms.push(Room {
            description: format!("Files related to {room}"),
            keywords: vec![room.clone()],
            name: room,
        });
        if rooms.len() >= 6 {
            break;
        }
    }

    if rooms.is_empty() {
        rooms.push(Room {
            name: "general".to_owned(),
            description: "All project files".to_owned(),
            keywords: vec![],
        });
    }
    rooms
}

fn walk_and_count(
    dir: &Path,
    skip: &std::collections::HashSet<&str>,
    counts: &mut HashMap<String, u32>,
) {
    let entries = match std::fs::read_dir(dir) {
        Ok(e) => e,
        Err(_) => return,
    };
    for entry in entries.flatten() {
        let path = entry.path();
        if path.is_dir() {
            let name = match path.file_name().and_then(|n| n.to_str()) {
                Some(n) => n.to_owned(),
                None => continue,
            };
            if !skip.contains(name.as_str()) {
                walk_and_count(&path, skip, counts);
            }
        } else if path.is_file() {
            let filename = match path.file_name().and_then(|n| n.to_str()) {
                Some(n) => n.to_owned(),
                None => continue,
            };
            let name_lower = filename.to_lowercase().replace('-', "_").replace(' ', "_");
            for (keyword, room) in FOLDER_ROOM_MAP.iter() {
                if name_lower.contains(keyword) {
                    *counts.entry((*room).to_owned()).or_insert(0) += 1;
                }
            }
        }
    }
}

pub fn print_proposed_structure(
    project_name: &str,
    rooms: &[Room],
    total_files: usize,
    source: &str,
    writer: &mut dyn Write,
) -> Result<(), std::io::Error> {
    writeln!(writer, "\n{}", "=".repeat(55))?;
    writeln!(writer, "  MemPalace Init — Local setup")?;
    writeln!(writer, "{}", "=".repeat(55))?;
    writeln!(writer, "\n  WING: {project_name}")?;
    writeln!(
        writer,
        "  ({total_files} files found, rooms detected from {source})\n"
    )?;
    for room in rooms {
        writeln!(writer, "    ROOM: {}", room.name)?;
        writeln!(writer, "          {}", room.description)?;
    }
    writeln!(writer, "\n{}", "─".repeat(55))?;
    Ok(())
}

fn read_trimmed(reader: &mut dyn BufRead) -> Result<String, std::io::Error> {
    let mut line = String::new();
    reader.read_line(&mut line)?;
    Ok(line.trim().to_owned())
}

pub fn get_user_approval(
    rooms: Vec<Room>,
    reader: &mut dyn BufRead,
    writer: &mut dyn Write,
) -> Vec<Room> {
    let _ = writeln!(writer, "  Review the proposed rooms above.");
    let _ = writeln!(writer, "  Options:");
    let _ = writeln!(writer, "    [enter]  Accept all rooms");
    let _ = writeln!(writer, "    [edit]   Remove or rename rooms");
    let _ = writeln!(writer, "    [add]    Add a room manually");
    let _ = writeln!(writer);
    let _ = write!(writer, "  Your choice [enter/edit/add]: ");
    let _ = writer.flush();
    let choice = read_trimmed(reader).unwrap_or_default().to_lowercase();

    if choice.is_empty() || choice == "y" || choice == "yes" {
        return rooms;
    }

    let mut rooms = rooms;

    if choice == "edit" {
        let _ = writeln!(writer, "\n  Current rooms:");
        for (i, room) in rooms.iter().enumerate() {
            let _ = writeln!(
                writer,
                "    {}. {} — {}",
                i + 1,
                room.name,
                room.description
            );
        }
        let _ = write!(
            writer,
            "\n  Room numbers to REMOVE (comma-separated, or enter to skip): "
        );
        let _ = writer.flush();
        let remove_str = read_trimmed(reader).unwrap_or_default();
        if !remove_str.is_empty() {
            let to_remove: std::collections::HashSet<usize> = remove_str
                .split(',')
                .filter_map(|s| s.trim().parse::<usize>().ok())
                .filter(|&n| n >= 1)
                .map(|n| n - 1)
                .collect();
            rooms = rooms
                .into_iter()
                .enumerate()
                .filter(|(i, _)| !to_remove.contains(i))
                .map(|(_, r)| r)
                .collect();
        }
    }

    let do_add = if choice == "add" {
        true
    } else {
        let _ = write!(writer, "\n  Add any missing rooms? [y/N]: ");
        let _ = writer.flush();
        read_trimmed(reader).unwrap_or_default().to_lowercase() == "y"
    };

    if do_add {
        loop {
            let _ = write!(writer, "  New room name (or enter to stop): ");
            let _ = writer.flush();
            let new_name = read_trimmed(reader)
                .unwrap_or_default()
                .to_lowercase()
                .replace(' ', "_");
            if new_name.is_empty() {
                break;
            }
            let _ = write!(writer, "  Description for '{new_name}': ");
            let _ = writer.flush();
            let new_desc = read_trimmed(reader).unwrap_or_default();
            rooms.push(Room {
                keywords: vec![new_name.clone()],
                description: new_desc,
                name: new_name,
            });
        }
    }

    rooms
}

#[derive(Serialize)]
struct RoomYaml {
    name: String,
    description: String,
    keywords: Vec<String>,
}

#[derive(Serialize)]
struct ConfigYaml {
    wing: String,
    rooms: Vec<RoomYaml>,
}

pub fn save_config(
    project_dir: &Path,
    project_name: &str,
    rooms: &[Room],
) -> Result<PathBuf, ModuleError> {
    let config = ConfigYaml {
        wing: project_name.to_owned(),
        rooms: rooms
            .iter()
            .map(|r| RoomYaml {
                name: r.name.clone(),
                description: r.description.clone(),
                keywords: if r.keywords.is_empty() {
                    vec![r.name.clone()]
                } else {
                    r.keywords.clone()
                },
            })
            .collect(),
    };

    let yaml_str = serde_yml::to_string(&config)?;
    let config_path = project_dir.join("mempalace.yaml");
    std::fs::write(&config_path, yaml_str)?;
    Ok(config_path)
}

fn count_project_files(project_dir: &Path) -> usize {
    let skip: std::collections::HashSet<&str> = SKIP_DIRS.iter().copied().collect();
    count_files_recursive(project_dir, &skip)
}

fn count_files_recursive(dir: &Path, skip: &std::collections::HashSet<&str>) -> usize {
    let entries = match std::fs::read_dir(dir) {
        Ok(e) => e,
        Err(_) => return 0,
    };
    let mut count = 0;
    for entry in entries.flatten() {
        let path = entry.path();
        if path.is_dir() {
            let name = path.file_name().and_then(|n| n.to_str()).unwrap_or("");
            if !skip.contains(name) {
                count += count_files_recursive(&path, skip);
            }
        } else if path.is_file() {
            count += 1;
        }
    }
    count
}

pub fn detect_rooms_local(
    project_dir: &Path,
    yes: bool,
    reader: &mut dyn BufRead,
    writer: &mut dyn Write,
) -> Result<(), ModuleError> {
    let project_path = project_dir
        .to_path_buf()
        .canonicalize()
        .unwrap_or_else(|_| project_dir.to_path_buf());

    if !project_path.exists() {
        return Err(ModuleError::NotFound(project_dir.to_path_buf()));
    }

    let project_name = project_path
        .file_name()
        .and_then(|n| n.to_str())
        .unwrap_or("project")
        .to_lowercase()
        .replace(' ', "_")
        .replace('-', "_");

    let total_files = count_project_files(&project_path);

    let mut rooms = detect_rooms_from_folders(&project_path);
    let mut source = "folder structure";

    if rooms.len() <= 1 {
        rooms = detect_rooms_from_files(&project_path);
        source = "filename patterns";
    }

    if rooms.is_empty() {
        rooms = vec![Room {
            name: "general".to_owned(),
            description: "All project files".to_owned(),
            keywords: vec![],
        }];
        source = "fallback (flat project)";
    }

    print_proposed_structure(&project_name, &rooms, total_files, source, writer)?;

    let approved = if yes {
        rooms
    } else {
        get_user_approval(rooms, reader, writer)
    };

    save_config(&project_path, &project_name, &approved)?;
    Ok(())
}

#[cfg(test)]
mod tests {
    #![allow(clippy::unwrap_used)]

    use super::*;
    use tempfile::tempdir;

    #[test]
    fn test_folder_room_map_has_expected_mappings() {
        assert_eq!(FOLDER_ROOM_MAP.get("frontend"), Some(&"frontend"));
        assert_eq!(FOLDER_ROOM_MAP.get("backend"), Some(&"backend"));
        assert_eq!(FOLDER_ROOM_MAP.get("docs"), Some(&"documentation"));
        assert_eq!(FOLDER_ROOM_MAP.get("tests"), Some(&"testing"));
        assert_eq!(FOLDER_ROOM_MAP.get("config"), Some(&"configuration"));
    }

    #[test]
    fn test_folder_room_map_alternative_names() {
        assert_eq!(FOLDER_ROOM_MAP.get("front-end"), Some(&"frontend"));
        assert_eq!(FOLDER_ROOM_MAP.get("back-end"), Some(&"backend"));
        assert_eq!(FOLDER_ROOM_MAP.get("server"), Some(&"backend"));
        assert_eq!(FOLDER_ROOM_MAP.get("client"), Some(&"frontend"));
        assert_eq!(FOLDER_ROOM_MAP.get("api"), Some(&"backend"));
    }

    #[test]
    fn test_detect_rooms_from_folders_standard_layout() {
        let dir = tempdir().unwrap();
        std::fs::create_dir(dir.path().join("frontend")).unwrap();
        std::fs::create_dir(dir.path().join("backend")).unwrap();
        std::fs::create_dir(dir.path().join("docs")).unwrap();
        let rooms = detect_rooms_from_folders(dir.path());
        let names: std::collections::HashSet<_> = rooms.iter().map(|r| r.name.as_str()).collect();
        assert!(names.contains("frontend"));
        assert!(names.contains("backend"));
        assert!(names.contains("documentation"));
    }

    #[test]
    fn test_detect_rooms_from_folders_always_has_general() {
        let dir = tempdir().unwrap();
        let rooms = detect_rooms_from_folders(dir.path());
        assert!(rooms.iter().any(|r| r.name == "general"));
    }

    #[test]
    fn test_detect_rooms_from_folders_empty_dir() {
        let dir = tempdir().unwrap();
        let rooms = detect_rooms_from_folders(dir.path());
        assert!(!rooms.is_empty());
        assert!(rooms.iter().any(|r| r.name == "general"));
    }

    #[test]
    fn test_detect_rooms_from_folders_skips_git() {
        let dir = tempdir().unwrap();
        std::fs::create_dir(dir.path().join(".git")).unwrap();
        std::fs::create_dir(dir.path().join("node_modules")).unwrap();
        std::fs::create_dir(dir.path().join("frontend")).unwrap();
        let rooms = detect_rooms_from_folders(dir.path());
        let names: std::collections::HashSet<_> = rooms.iter().map(|r| r.name.as_str()).collect();
        assert!(!names.contains(".git"));
        assert!(!names.contains("node_modules"));
    }

    #[test]
    fn test_detect_rooms_from_folders_nested_dirs() {
        let dir = tempdir().unwrap();
        let src = dir.path().join("src");
        std::fs::create_dir(&src).unwrap();
        std::fs::create_dir(src.join("components")).unwrap();
        std::fs::create_dir(src.join("routes")).unwrap();
        let rooms = detect_rooms_from_folders(dir.path());
        let names: std::collections::HashSet<_> = rooms.iter().map(|r| r.name.as_str()).collect();
        assert!(names.contains("frontend") || names.contains("backend"));
    }

    #[test]
    fn test_detect_rooms_from_folders_room_has_description() {
        let dir = tempdir().unwrap();
        std::fs::create_dir(dir.path().join("docs")).unwrap();
        let rooms = detect_rooms_from_folders(dir.path());
        let doc_room = rooms.iter().find(|r| r.name == "documentation");
        assert!(doc_room.is_some());
        let doc_room = doc_room.unwrap();
        assert!(doc_room.description.contains("docs"));
    }

    #[test]
    fn test_detect_rooms_from_folders_room_has_keywords() {
        let dir = tempdir().unwrap();
        std::fs::create_dir(dir.path().join("frontend")).unwrap();
        let rooms = detect_rooms_from_folders(dir.path());
        let fe = rooms.iter().find(|r| r.name == "frontend");
        assert!(fe.is_some());
        assert!(!fe.unwrap().keywords.is_empty());
    }

    #[test]
    fn test_detect_rooms_from_folders_custom_named_dirs() {
        let dir = tempdir().unwrap();
        std::fs::create_dir(dir.path().join("mylib")).unwrap();
        let rooms = detect_rooms_from_folders(dir.path());
        let names: std::collections::HashSet<_> = rooms.iter().map(|r| r.name.as_str()).collect();
        assert!(names.contains("mylib") || names.contains("general"));
    }

    #[test]
    fn test_detect_rooms_from_files_with_matching_filenames() {
        let dir = tempdir().unwrap();
        for name in &["test_auth.py", "test_login.py", "test_api.py"] {
            std::fs::write(dir.path().join(name), "content").unwrap();
        }
        let rooms = detect_rooms_from_files(dir.path());
        let names: std::collections::HashSet<_> = rooms.iter().map(|r| r.name.as_str()).collect();
        assert!(names.contains("testing") || names.contains("general"));
    }

    #[test]
    fn test_detect_rooms_from_files_empty_dir() {
        let dir = tempdir().unwrap();
        let rooms = detect_rooms_from_files(dir.path());
        assert!(!rooms.is_empty());
        assert!(rooms.iter().any(|r| r.name == "general"));
    }

    #[test]
    fn test_detect_rooms_from_files_caps_at_six() {
        let dir = tempdir().unwrap();
        for keyword in &[
            "test", "doc", "api", "config", "frontend", "backend", "design", "meeting",
        ] {
            for i in 0..3 {
                std::fs::write(
                    dir.path().join(format!("{keyword}_file_{i}.txt")),
                    "content",
                )
                .unwrap();
            }
        }
        let rooms = detect_rooms_from_files(dir.path());
        assert!(rooms.len() <= 6);
    }

    #[test]
    fn test_save_config_creates_yaml() {
        let dir = tempdir().unwrap();
        let rooms = vec![
            Room {
                name: "frontend".to_owned(),
                description: "UI files".to_owned(),
                keywords: vec!["frontend".to_owned()],
            },
            Room {
                name: "backend".to_owned(),
                description: "Server files".to_owned(),
                keywords: vec!["backend".to_owned()],
            },
        ];
        let path = save_config(dir.path(), "myproject", &rooms).unwrap();
        assert!(path.exists());
        let content = std::fs::read_to_string(&path).unwrap();
        assert!(content.contains("myproject"));
        assert!(content.contains("frontend"));
        assert!(content.contains("backend"));
    }

    #[test]
    fn test_save_config_valid_yaml() {
        let dir = tempdir().unwrap();
        let rooms = vec![Room {
            name: "general".to_owned(),
            description: "All files".to_owned(),
            keywords: vec![],
        }];
        let path = save_config(dir.path(), "test_proj", &rooms).unwrap();
        let content = std::fs::read_to_string(&path).unwrap();
        assert!(content.contains("test_proj"));
        assert!(content.contains("general"));
    }

    #[test]
    fn test_print_proposed_structure() {
        let rooms = vec![
            Room {
                name: "frontend".to_owned(),
                description: "UI files".to_owned(),
                keywords: vec![],
            },
            Room {
                name: "general".to_owned(),
                description: "Everything else".to_owned(),
                keywords: vec![],
            },
        ];
        let mut output = Vec::new();
        print_proposed_structure("myapp", &rooms, 42, "folder structure", &mut output).unwrap();
        let out = String::from_utf8(output).unwrap();
        assert!(out.contains("myapp"));
        assert!(out.contains("frontend"));
        assert!(out.contains("42 files"));
        assert!(out.contains("folder structure"));
    }

    #[test]
    fn test_get_user_approval_accept_all() {
        let rooms = vec![Room {
            name: "frontend".to_owned(),
            description: "UI".to_owned(),
            keywords: vec![],
        }];
        let result = get_user_approval(rooms.clone(), &mut "\n".as_bytes(), &mut Vec::new());
        assert_eq!(result.len(), 1);
        assert_eq!(result[0].name, "frontend");
    }

    #[test]
    fn test_get_user_approval_edit_remove() {
        let rooms = vec![
            Room {
                name: "frontend".to_owned(),
                description: "UI".to_owned(),
                keywords: vec![],
            },
            Room {
                name: "backend".to_owned(),
                description: "Server".to_owned(),
                keywords: vec![],
            },
        ];
        let input = "edit\n1\nn\n";
        let result = get_user_approval(rooms, &mut input.as_bytes(), &mut Vec::new());
        assert_eq!(result.len(), 1);
        assert_eq!(result[0].name, "backend");
    }

    #[test]
    fn test_get_user_approval_add_room() {
        let rooms = vec![Room {
            name: "general".to_owned(),
            description: "All files".to_owned(),
            keywords: vec![],
        }];
        let input = "add\ncustom_room\nMy custom room\n\n";
        let result = get_user_approval(rooms, &mut input.as_bytes(), &mut Vec::new());
        let names: Vec<_> = result.iter().map(|r| r.name.as_str()).collect();
        assert!(names.contains(&"custom_room"));
    }

    #[test]
    fn test_detect_rooms_local_yes_mode() {
        let dir = tempdir().unwrap();
        std::fs::create_dir(dir.path().join("docs")).unwrap();
        std::fs::write(dir.path().join("docs").join("readme.md"), "hello").unwrap();
        detect_rooms_local(dir.path(), true, &mut "".as_bytes(), &mut Vec::new()).unwrap();
        assert!(dir.path().join("mempalace.yaml").exists());
    }

    #[test]
    fn test_detect_rooms_local_fallback_to_files() {
        let dir = tempdir().unwrap();
        for i in 0..3 {
            std::fs::write(dir.path().join(format!("test_file_{i}.py")), "content").unwrap();
        }
        detect_rooms_local(dir.path(), true, &mut "".as_bytes(), &mut Vec::new()).unwrap();
        assert!(dir.path().join("mempalace.yaml").exists());
    }

    #[test]
    fn test_detect_rooms_local_missing_dir() {
        let result = detect_rooms_local(
            Path::new("/nonexistent/path/that/does/not/exist"),
            true,
            &mut "".as_bytes(),
            &mut Vec::new(),
        );
        assert!(result.is_err());
    }

    #[test]
    fn test_detect_rooms_local_interactive() {
        let dir = tempdir().unwrap();
        let src = dir.path().join("src");
        std::fs::create_dir(&src).unwrap();
        std::fs::write(src.join("main.py"), "code").unwrap();
        let input = "\n";
        detect_rooms_local(dir.path(), false, &mut input.as_bytes(), &mut Vec::new()).unwrap();
        assert!(dir.path().join("mempalace.yaml").exists());
    }
}
