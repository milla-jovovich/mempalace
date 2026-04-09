#![forbid(unsafe_code)]
#![allow(clippy::pedantic)]
#![allow(clippy::unwrap_used)]
#![allow(clippy::expect_used)]
#![allow(clippy::panic)]
#![allow(clippy::useless_vec)]
#![allow(clippy::manual_split_once)]
#![allow(clippy::needless_splitn)]
#![allow(clippy::collapsible_if)]
#![allow(clippy::collapsible_match)]
#![allow(clippy::collapsible_else_if)]
#![allow(clippy::type_complexity)]
#![allow(clippy::manual_strip)]
#![allow(clippy::collapsible_str_replace)]
#![allow(clippy::unnecessary_map_or)]
#![allow(clippy::option_map_or_none)]
#![allow(clippy::bind_instead_of_map)]
#![doc = "Text processing: AAAK dialect, normalization, entity detection, extractors, spellcheck."]

pub mod dialect;
pub mod entity_detector;
pub mod entity_registry;
pub mod general_extractor;
pub mod normalize;
pub mod room_detector;
pub mod spellcheck;
pub mod split_mega_files;

pub use mempalace_core::VERSION;
