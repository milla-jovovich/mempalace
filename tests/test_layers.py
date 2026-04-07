from mempalace.layers import Layer0, Layer1, Layer2, Layer3, MemoryStack


def test_layer0_renders_identity_file(tmp_dir):
    identity = tmp_dir / "identity.txt"
    identity.write_text("I am Atlas, a personal AI assistant.")
    l0 = Layer0(identity_path=str(identity))
    assert "Atlas" in l0.render()


def test_layer0_default_when_missing(tmp_dir):
    l0 = Layer0(identity_path=str(tmp_dir / "nonexistent.txt"))
    result = l0.render()
    assert "No identity configured" in result


def test_layer0_token_estimate(tmp_dir):
    identity = tmp_dir / "identity.txt"
    identity.write_text("x" * 400)
    l0 = Layer0(identity_path=str(identity))
    assert l0.token_estimate() == 100  # 400 chars / 4


def test_layer1_generates_from_palace(populated_palace):
    palace_path, _ = populated_palace
    l1 = Layer1(palace_path=palace_path)
    text = l1.generate()
    assert "L1" in text


def test_layer1_no_palace(tmp_dir):
    l1 = Layer1(palace_path=str(tmp_dir / "empty"))
    text = l1.generate()
    assert "No palace found" in text


def test_layer2_retrieve_by_wing(populated_palace):
    palace_path, _ = populated_palace
    l2 = Layer2(palace_path=palace_path)
    text = l2.retrieve(wing="family")
    assert "L2" in text
    assert "drawers" in text


def test_layer2_no_results(populated_palace):
    palace_path, _ = populated_palace
    l2 = Layer2(palace_path=palace_path)
    text = l2.retrieve(wing="nonexistent_wing")
    assert "No drawers found" in text


def test_layer3_search(populated_palace):
    palace_path, _ = populated_palace
    l3 = Layer3(palace_path=palace_path)
    text = l3.search("chess")
    assert "L3" in text
    assert "chess" in text.lower() or "alice" in text.lower()


def test_layer3_search_raw(populated_palace):
    palace_path, _ = populated_palace
    l3 = Layer3(palace_path=palace_path)
    hits = l3.search_raw("chess")
    assert len(hits) > 0
    assert "text" in hits[0]
    assert "similarity" in hits[0]


def test_memory_stack_wake_up(tmp_dir, populated_palace):
    palace_path, _ = populated_palace
    identity = tmp_dir / "identity.txt"
    identity.write_text("I am Atlas.")
    stack = MemoryStack(palace_path=palace_path, identity_path=str(identity))
    text = stack.wake_up()
    assert "Atlas" in text
    assert "L1" in text


def test_memory_stack_status(populated_palace):
    palace_path, _ = populated_palace
    stack = MemoryStack(palace_path=palace_path)
    status = stack.status()
    assert status["total_drawers"] == 4
    assert status["L0_identity"]["exists"] is False
