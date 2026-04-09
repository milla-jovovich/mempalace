#![allow(clippy::unwrap_used, clippy::expect_used)]

use assert_cmd::Command;
use predicates::prelude::*;
use tempfile::TempDir;

fn bin() -> Command {
    Command::cargo_bin("mempalace").unwrap()
}

#[test]
fn prints_version() {
    bin()
        .arg("--version")
        .assert()
        .success()
        .stdout(predicate::str::contains(mempalace_core::VERSION));
}

#[test]
fn help_lists_subcommands() {
    bin()
        .arg("--help")
        .assert()
        .success()
        .stdout(predicate::str::contains("status"))
        .stdout(predicate::str::contains("search"))
        .stdout(predicate::str::contains("mine"))
        .stdout(predicate::str::contains("wake-up"));
}

#[test]
fn status_runs() {
    bin()
        .arg("status")
        .assert()
        .success()
        .stdout(predicate::str::contains("mempalace"))
        .stdout(predicate::str::contains("drawers:"));
}

#[test]
fn search_on_empty_palace_prints_no_results() {
    bin()
        .args(["search", "anything"])
        .assert()
        .success()
        .stdout(predicate::str::contains("No results"));
}

#[test]
fn mine_errors_on_missing_directory() {
    bin()
        .args(["mine", "/definitely/does/not/exist"])
        .assert()
        .failure();
}

#[test]
fn mine_empty_directory_succeeds() {
    let tmp = TempDir::new().unwrap();
    bin()
        .args(["mine", tmp.path().to_str().unwrap()])
        .assert()
        .success();
}

#[test]
fn mcp_prints_setup_command() {
    bin()
        .arg("mcp")
        .assert()
        .success()
        .stdout(predicate::str::contains("claude mcp add mempalace"));
}

#[test]
fn instructions_prints_version() {
    bin()
        .arg("instructions")
        .assert()
        .success()
        .stdout(predicate::str::contains(mempalace_core::VERSION));
}

#[test]
fn unknown_subcommand_is_error() {
    bin().arg("nonexistent-subcmd").assert().failure();
}

#[test]
fn wake_up_prints_identity_section() {
    bin()
        .arg("wake-up")
        .assert()
        .success()
        .stdout(predicate::str::contains("L0"));
}

#[test]
fn hook_save_requires_content() {
    bin().arg("hook-save").assert().failure();
}

#[test]
fn hook_save_accepts_content() {
    bin()
        .args(["hook-save", "some content worth saving"])
        .assert()
        .success()
        .stdout(predicate::str::contains("chars_written"));
}

#[test]
fn split_handles_empty_directory() {
    let tmp = TempDir::new().unwrap();
    bin()
        .args(["split", tmp.path().to_str().unwrap()])
        .assert()
        .success();
}
