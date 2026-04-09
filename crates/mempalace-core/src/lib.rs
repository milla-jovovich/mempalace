#![forbid(unsafe_code)]
#![doc = "Core primitives for mempalace: version, config, sanitization, path helpers."]

pub const VERSION: &str = "3.1.0";

#[cfg(test)]
mod tests {
    use super::VERSION;

    #[test]
    fn version_matches_workspace() {
        assert_eq!(VERSION, "3.1.0");
    }
}
