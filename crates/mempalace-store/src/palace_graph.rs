//! Room-based navigation graph built on top of the palace.
//!
//! Port of Python `mempalace/palace_graph.py`.

use std::collections::{BTreeMap, BTreeSet, HashMap};

use serde::{Deserialize, Serialize};

use crate::palace::{Palace, SearchFilter};

#[derive(Debug, Clone, Default, Serialize, Deserialize)]
pub struct GraphNode {
    pub wings: Vec<String>,
    pub halls: Vec<String>,
    pub count: usize,
    pub dates: Vec<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct GraphEdge {
    pub room: String,
    pub wing_a: String,
    pub wing_b: String,
    pub hall: String,
    pub count: usize,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct TraversalHit {
    pub room: String,
    pub wings: Vec<String>,
    pub halls: Vec<String>,
    pub count: usize,
    pub hop: usize,
    pub connected_via: Vec<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Tunnel {
    pub room: String,
    pub wings: Vec<String>,
    pub halls: Vec<String>,
    pub count: usize,
    pub recent: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct GraphStats {
    pub total_rooms: usize,
    pub tunnel_rooms: usize,
    pub total_edges: usize,
    pub rooms_per_wing: BTreeMap<String, usize>,
    pub top_tunnels: Vec<TopTunnel>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct TopTunnel {
    pub room: String,
    pub wings: Vec<String>,
    pub count: usize,
}

#[derive(Debug, Default)]
struct RoomAccumulator {
    wings: BTreeSet<String>,
    halls: BTreeSet<String>,
    dates: BTreeSet<String>,
    count: usize,
}

#[derive(Debug)]
pub struct PalaceGraph<'p> {
    palace: &'p dyn Palace,
}

impl<'p> PalaceGraph<'p> {
    pub fn new(palace: &'p dyn Palace) -> Self {
        Self { palace }
    }

    pub fn build(&self) -> (HashMap<String, GraphNode>, Vec<GraphEdge>) {
        let drawers = self
            .palace
            .list_filtered(&SearchFilter::default(), usize::MAX)
            .unwrap_or_default();

        let mut rooms: HashMap<String, RoomAccumulator> = HashMap::new();
        for d in &drawers {
            let room = match d.metadata.room.as_deref() {
                Some(r) if !r.is_empty() && r != "general" => r.to_string(),
                _ => continue,
            };
            let wing = match d.metadata.wing.as_deref() {
                Some(w) if !w.is_empty() => w.to_string(),
                _ => continue,
            };
            let entry = rooms.entry(room).or_default();
            entry.wings.insert(wing);
            if let Some(h) = d.metadata.hall.as_deref() {
                if !h.is_empty() {
                    entry.halls.insert(h.to_string());
                }
            }
            if let Some(dt) = d.metadata.date.as_deref() {
                if !dt.is_empty() {
                    entry.dates.insert(dt.to_string());
                }
            }
            entry.count += 1;
        }

        let mut edges: Vec<GraphEdge> = Vec::new();
        for (room, data) in &rooms {
            let wings: Vec<String> = data.wings.iter().cloned().collect();
            if wings.len() < 2 {
                continue;
            }
            for (i, wa) in wings.iter().enumerate() {
                for wb in &wings[i + 1..] {
                    for hall in &data.halls {
                        edges.push(GraphEdge {
                            room: room.clone(),
                            wing_a: wa.clone(),
                            wing_b: wb.clone(),
                            hall: hall.clone(),
                            count: data.count,
                        });
                    }
                }
            }
        }

        let nodes: HashMap<String, GraphNode> = rooms
            .into_iter()
            .map(|(room, acc)| {
                let mut dates: Vec<String> = acc.dates.into_iter().collect();
                let start = dates.len().saturating_sub(5);
                let recent: Vec<String> = dates.drain(start..).collect();
                (
                    room,
                    GraphNode {
                        wings: acc.wings.into_iter().collect(),
                        halls: acc.halls.into_iter().collect(),
                        count: acc.count,
                        dates: recent,
                    },
                )
            })
            .collect();

        (nodes, edges)
    }

    pub fn traverse(&self, start_room: &str, max_hops: usize) -> Vec<TraversalHit> {
        let (nodes, _) = self.build();
        let Some(start) = nodes.get(start_room) else {
            return Vec::new();
        };

        let mut visited: BTreeSet<String> = BTreeSet::new();
        visited.insert(start_room.to_string());
        let mut results = vec![TraversalHit {
            room: start_room.to_string(),
            wings: start.wings.clone(),
            halls: start.halls.clone(),
            count: start.count,
            hop: 0,
            connected_via: Vec::new(),
        }];

        let mut frontier: Vec<(String, usize)> = vec![(start_room.to_string(), 0)];

        while let Some((current_room, depth)) = {
            if frontier.is_empty() {
                None
            } else {
                Some(frontier.remove(0))
            }
        } {
            if depth >= max_hops {
                continue;
            }
            let current = match nodes.get(&current_room) {
                Some(n) => n,
                None => continue,
            };
            let current_wings: BTreeSet<&String> = current.wings.iter().collect();

            for (room, data) in &nodes {
                if visited.contains(room) {
                    continue;
                }
                let other: BTreeSet<&String> = data.wings.iter().collect();
                let shared: Vec<String> = current_wings
                    .intersection(&other)
                    .map(|s| (*s).clone())
                    .collect();
                if shared.is_empty() {
                    continue;
                }
                visited.insert(room.clone());
                results.push(TraversalHit {
                    room: room.clone(),
                    wings: data.wings.clone(),
                    halls: data.halls.clone(),
                    count: data.count,
                    hop: depth + 1,
                    connected_via: shared,
                });
                if depth + 1 < max_hops {
                    frontier.push((room.clone(), depth + 1));
                }
            }
        }

        results.sort_by(|a, b| a.hop.cmp(&b.hop).then_with(|| b.count.cmp(&a.count)));
        results.truncate(50);
        results
    }

    pub fn find_tunnels(&self, wing_a: Option<&str>, wing_b: Option<&str>) -> Vec<Tunnel> {
        let (nodes, _) = self.build();
        let mut tunnels: Vec<Tunnel> = nodes
            .into_iter()
            .filter_map(|(room, data)| {
                if data.wings.len() < 2 {
                    return None;
                }
                if let Some(wa) = wing_a {
                    if !data.wings.iter().any(|w| w == wa) {
                        return None;
                    }
                }
                if let Some(wb) = wing_b {
                    if !data.wings.iter().any(|w| w == wb) {
                        return None;
                    }
                }
                let recent = data.dates.last().cloned().unwrap_or_default();
                Some(Tunnel {
                    room,
                    wings: data.wings,
                    halls: data.halls,
                    count: data.count,
                    recent,
                })
            })
            .collect();

        tunnels.sort_by(|a, b| b.count.cmp(&a.count));
        tunnels.truncate(50);
        tunnels
    }

    pub fn stats(&self) -> GraphStats {
        let (nodes, edges) = self.build();
        let tunnel_rooms = nodes.values().filter(|n| n.wings.len() >= 2).count();

        let mut wing_counts: BTreeMap<String, usize> = BTreeMap::new();
        for node in nodes.values() {
            for w in &node.wings {
                *wing_counts.entry(w.clone()).or_insert(0) += 1;
            }
        }

        let mut sorted_nodes: Vec<(&String, &GraphNode)> = nodes.iter().collect();
        sorted_nodes.sort_by(|a, b| b.1.wings.len().cmp(&a.1.wings.len()));

        let top_tunnels: Vec<TopTunnel> = sorted_nodes
            .into_iter()
            .filter(|(_, n)| n.wings.len() >= 2)
            .take(10)
            .map(|(room, n)| TopTunnel {
                room: room.clone(),
                wings: n.wings.clone(),
                count: n.count,
            })
            .collect();

        GraphStats {
            total_rooms: nodes.len(),
            tunnel_rooms,
            total_edges: edges.len(),
            rooms_per_wing: wing_counts,
            top_tunnels,
        }
    }
}
