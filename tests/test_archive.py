import unittest
from unittest.mock import MagicMock
from mempalace.archive import archive_noise
from mempalace.knowledge_graph import KnowledgeGraph


class TestArchiveNoise(unittest.TestCase):
    def test_archive_noise_empty(self):
        col = MagicMock()
        kg = MagicMock(spec=KnowledgeGraph)

        result = archive_noise(col, kg, "test_room", [])
        self.assertEqual(result, 0)
        col.get.assert_not_called()
        kg.add_entity.assert_not_called()

    def test_archive_noise_no_ids_returned(self):
        col = MagicMock()
        col.get.return_value = {"ids": [], "metadatas": []}
        kg = MagicMock(spec=KnowledgeGraph)

        result = archive_noise(col, kg, "test_room", ["id1"])
        self.assertEqual(result, 0)
        col.get.assert_called_once_with(ids=["id1"])
        col.update.assert_not_called()
        kg.add_entity.assert_not_called()

    def test_archive_noise_success(self):
        col = MagicMock()
        col.get.return_value = {"ids": ["id1", "id2"], "metadatas": [{"wing": "main"}, None]}
        kg = MagicMock(spec=KnowledgeGraph)

        result = archive_noise(col, kg, "test_room", ["id1", "id2"])

        self.assertEqual(result, 2)
        col.get.assert_called_once_with(ids=["id1", "id2"])

        # Check col.update call
        col.update.assert_called_once()
        update_kwargs = col.update.call_args[1]
        self.assertEqual(update_kwargs["ids"], ["id1", "id2"])
        metadatas = update_kwargs["metadatas"]
        self.assertEqual(len(metadatas), 2)
        self.assertEqual(metadatas[0]["wing"], "archive")
        self.assertEqual(metadatas[0]["original_wing"], "main")
        self.assertIn("crystallized_at", metadatas[0])
        self.assertEqual(metadatas[1]["wing"], "archive")
        self.assertIn("crystallized_at", metadatas[1])

        # Check KG updates
        self.assertEqual(kg.add_entity.call_count, 2)
        kg.add_entity.assert_any_call("test_room", "room")
        kg.add_entity.assert_any_call("test_room_archive", "room")

        kg.add_triple.assert_called_once_with("test_room", "has_archive", "test_room_archive")

    def test_archive_preserves_original_metadata(self):
        col = MagicMock()
        kg = MagicMock(spec=KnowledgeGraph)

        col.get.return_value = {
            "ids": ["doc_1"],
            "metadatas": [{"wing": "work", "room": "ideas", "extra": "data"}],
        }

        archive_noise(col, kg, "ideas", ["doc_1"])

        update_kwargs = col.update.call_args[1]
        meta = update_kwargs["metadatas"][0]

        self.assertEqual(meta["wing"], "archive")
        self.assertEqual(meta["original_wing"], "work")
        self.assertEqual(meta["original_room"], "ideas")
        self.assertEqual(meta["extra"], "data")

    def test_archive_adds_crystallized_at(self):
        col = MagicMock()
        kg = MagicMock(spec=KnowledgeGraph)

        col.get.return_value = {
            "ids": ["doc_1"],
            "metadatas": [{"wing": "main", "room": "ideas"}],
        }

        archive_noise(col, kg, "ideas", ["doc_1"])

        update_kwargs = col.update.call_args[1]
        meta = update_kwargs["metadatas"][0]

        self.assertIn("crystallized_at", meta)
        self.assertIsInstance(meta["crystallized_at"], str)


if __name__ == "__main__":
    unittest.main()
