import json
import tempfile
import unittest
from datetime import timedelta
from pathlib import Path
from unittest import mock

from scribe.sessions import SessionStore


class SessionStoreTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.folder = Path(self._tmp.name)
        self.store = SessionStore(self.folder)

    def tearDown(self):
        self._tmp.cleanup()

    def txt_files(self):
        return sorted(p.name for p in self.folder.glob("*.txt"))

    def test_repeated_saves_keep_one_file_per_meeting(self):
        session = self.store.create()
        for i in range(20):
            session.add_text(i * 5.0, i * 5.0 + 2, f"Phrase {i}.", None)
            self.store.save(session)
        self.assertEqual(len(self.txt_files()), 1)
        self.assertEqual(len(list(self.store.data_dir.glob("*.json"))), 1)
        self.assertIn("Phrase 19.", (self.folder / session.txt_name).read_text())
        self.assertEqual(list(self.folder.glob(".*.tmp")), [])

    def test_renaming_moves_the_readable_file(self):
        session = self.store.create()
        session.add_text(0, 2, "Hello.", None)
        self.store.save(session)
        old = session.txt_name
        session.set_title("Weekly sync: planning/review")
        self.store.save(session)
        self.assertEqual(self.txt_files(), [session.txt_name])
        self.assertNotEqual(old, session.txt_name)
        self.assertTrue(session.txt_name.endswith("Weekly sync planning review.txt"))

    def test_two_untitled_meetings_in_the_same_minute_get_separate_files(self):
        first = self.store.create()
        second = self.store.create()
        self.assertNotEqual(first.id, second.id)
        for session in (first, second):
            session.add_text(0, 1, "Hi.", None)
            self.store.save(session)
        self.assertEqual(len(self.txt_files()), 2)

    def test_meetings_without_speech_leave_no_files(self):
        session = self.store.create(title="Nobody spoke")
        self.assertIsNone(self.store.save(session))
        self.assertEqual(self.txt_files(), [])
        self.assertEqual(list(self.store.data_dir.glob("*.json")), [])

    def test_discard_removes_both_files(self):
        session = self.store.create()
        session.add_text(0, 1, "Hi.", None)
        self.store.save(session)
        self.store.discard(session)
        self.assertEqual(self.txt_files(), [])
        self.assertEqual(list(self.store.data_dir.glob("*.json")), [])

    def test_trash_removes_the_meeting_but_keeps_its_files_recoverable(self):
        session = self.store.create()
        session.add_text(0, 1, "Delete me.", None)
        self.store.save(session)
        with mock.patch("scribe.sessions.shutil.which", return_value=None):  # no desktop Trash
            self.store.trash(session)
        self.assertEqual(self.txt_files(), [])
        self.assertEqual(self.store.list_meetings(), [])
        kept = sorted(p.suffix for p in (self.store.data_dir / "deleted").iterdir())
        self.assertEqual(kept, [".json", ".txt"])

    def test_round_trip_and_search(self):
        session = self.store.create(title="Budget")
        session.add_text(0, 2, "We need more cowbell.", "You")
        self.store.save(session)
        loaded = self.store.load(session.id)
        self.assertEqual(loaded.blocks[0].text, "We need more cowbell.")
        self.assertEqual(loaded.blocks[0].speaker, "You")
        self.assertEqual([m["id"] for m in self.store.list_meetings("cowbell")], [session.id])
        self.assertEqual(self.store.list_meetings("tambourine"), [])

    def test_list_is_newest_first_by_start_time(self):
        later, earlier = self.store.create(title="Later"), self.store.create(title="Earlier")
        earlier.started_at = later.started_at - timedelta(days=1)
        for session in (later, earlier):
            session.add_text(0, 1, "Hi.", None)
            self.store.save(session)
        self.assertEqual([m["title"] for m in self.store.list_meetings()], ["Later", "Earlier"])

    def test_unsafe_ids_are_rejected(self):
        with self.assertRaises(KeyError):
            self.store.load("../../etc/passwd")

    def test_json_is_valid_after_save(self):
        session = self.store.create()
        session.add_text(0, 1, "Ünïcode ✓", None)
        self.store.save(session)
        data = json.loads((self.store.data_dir / f"{session.id}.json").read_text())
        self.assertEqual(data["blocks"][0]["text"], "Ünïcode ✓")


class ParagraphTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.session = SessionStore(Path(self._tmp.name)).create()

    def tearDown(self):
        self._tmp.cleanup()

    def test_close_phrases_join_and_long_pauses_split(self):
        s = self.session
        s.add_text(0.0, 2.0, "One.", None)
        s.add_text(2.5, 4.0, "Two.", None)
        s.add_text(10.0, 11.0, "Three.", None)
        self.assertEqual([b.text for b in s.blocks], ["One. Two.", "Three."])

    def test_speaker_change_starts_a_paragraph(self):
        s = self.session
        s.add_text(0.0, 2.0, "Hi.", "You")
        s.add_text(2.2, 3.0, "Hello.", "Others")
        self.assertEqual(len(s.blocks), 2)

    def test_edit_keeps_speech_that_arrived_while_typing(self):
        s = self.session
        block = s.add_text(0.0, 2.0, "Helo wrld.", None)
        s.add_text(2.2, 3.0, "And more.", None)
        s.edit_block(block.id, "Hello world.", base_text="Helo wrld.")
        self.assertEqual(block.text, "Hello world. And more.")
        # New speech after an edit starts a new paragraph rather than changing the edited one.
        s.add_text(3.2, 4.0, "Later.", None)
        self.assertEqual(len(s.blocks), 2)


if __name__ == "__main__":
    unittest.main()
