//! Integration test for `mempalace mcp-serve`.
//!
//! Spawns the binary, pipes JSON-RPC initialize + tools/list requests, and
//! asserts the responses contain the expected tool names.

#![forbid(unsafe_code)]
#![allow(clippy::unwrap_used, clippy::expect_used)]

use std::io::{BufRead, BufReader, Write};
use std::process::{Command, Stdio};
use std::time::Duration;

#[test]
#[allow(clippy::too_many_lines)]
fn mcp_serve_initialize_and_list_tools() {
    // Build the input: initialize request, initialized notification, tools/list request.
    let initialize_req = r#"{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"test","version":"0"}}}"#;
    let initialized_notif = r#"{"jsonrpc":"2.0","method":"notifications/initialized","params":{}}"#;
    let list_tools_req = r#"{"jsonrpc":"2.0","id":2,"method":"tools/list","params":{}}"#;

    // Resolve the binary from the cargo build artifacts.
    let bin = assert_cmd::cargo::cargo_bin("mempalace");

    let mut child = Command::new(&bin)
        .arg("mcp-serve")
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::null())
        .spawn()
        .expect("failed to spawn mempalace mcp-serve");

    let mut stdin = child.stdin.take().expect("stdin not captured");
    let stdout = child.stdout.take().expect("stdout not captured");

    // Read responses in a background thread
    let reader_handle = std::thread::spawn(move || {
        let reader = BufReader::new(stdout);
        let mut responses: Vec<serde_json::Value> = Vec::new();
        let deadline = std::time::Instant::now() + Duration::from_secs(10);

        for line_result in reader.lines() {
            if std::time::Instant::now() > deadline {
                break;
            }
            let Ok(line) = line_result else { break };
            let trimmed = line.trim();
            if trimmed.is_empty() {
                continue;
            }
            if let Ok(val) = serde_json::from_str::<serde_json::Value>(trimmed) {
                if val.get("id").is_some() {
                    responses.push(val);
                }
            }
            if responses.len() >= 2 {
                break;
            }
        }

        responses
    });

    // Send initialize request
    writeln!(stdin, "{initialize_req}").expect("write init");
    stdin.flush().expect("flush");

    // rmcp's serve_server reads initialize, sends response, then waits for
    // the initialized notification. A short delay ensures the server has
    // transitioned to the notification-wait state before we send it.
    std::thread::sleep(Duration::from_millis(500));

    // Send initialized notification + tools/list request
    writeln!(stdin, "{initialized_notif}").expect("write notif");
    stdin.flush().expect("flush");

    std::thread::sleep(Duration::from_millis(200));

    writeln!(stdin, "{list_tools_req}").expect("write tools/list");
    stdin.flush().expect("flush");

    // Give server time to respond before we signal EOF
    std::thread::sleep(Duration::from_millis(500));

    // Drop stdin to signal EOF
    drop(stdin);

    let responses = reader_handle.join().expect("reader thread panicked");

    // Kill the child in case it's still running.
    let _ = child.kill();
    let _ = child.wait();

    assert!(
        responses.len() >= 2,
        "expected at least 2 responses, got {}: {responses:#?}",
        responses.len(),
    );

    // Response 1: initialize result
    let init_resp = &responses[0];
    assert_eq!(
        init_resp.get("id").and_then(serde_json::Value::as_i64),
        Some(1),
        "first response should have id=1"
    );
    let init_result = init_resp
        .get("result")
        .expect("initialize response missing result");
    assert!(
        init_result.get("serverInfo").is_some(),
        "initialize result should have serverInfo"
    );
    assert!(
        init_result.get("capabilities").is_some(),
        "initialize result should have capabilities"
    );

    // Response 2: tools/list result
    let tools_resp = &responses[1];
    assert_eq!(
        tools_resp.get("id").and_then(serde_json::Value::as_i64),
        Some(2),
        "second response should have id=2"
    );
    let tools_result = tools_resp
        .get("result")
        .expect("tools/list response missing result");
    let tools = tools_result
        .get("tools")
        .and_then(|v| v.as_array())
        .expect("tools/list result should have tools array");

    // Check that at least mempalace_status and mempalace_search are present
    let tool_names: Vec<&str> = tools
        .iter()
        .filter_map(|t| t.get("name").and_then(|n| n.as_str()))
        .collect();

    assert!(
        tool_names.contains(&"mempalace_status"),
        "tools should include mempalace_status, got: {tool_names:?}",
    );
    assert!(
        tool_names.contains(&"mempalace_search"),
        "tools should include mempalace_search, got: {tool_names:?}",
    );

    // Verify we have a reasonable number of tools (17 expected)
    assert!(
        tool_names.len() >= 15,
        "expected at least 15 tools, got {}: {tool_names:?}",
        tool_names.len(),
    );
}
