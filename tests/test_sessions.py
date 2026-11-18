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

    def test_archived_meetings_are_kept_but_listed_apart(self):
        kept, put_away = self.store.create(title="Kept"), self.store.create(title="Put away")
        for session in (kept, put_away):
            session.add_text(0, 1, "Quarterly numbers.", None)
            self.store.save(session)
        put_away.set_archived(True)
        self.store.save(put_away)
        self.assertEqual([m["title"] for m in self.store.list_meetings()], ["Kept"])
        self.assertEqual([m["title"] for m in self.store.list_meetings(archived=True)], ["Put away"])
        self.assertEqual([m["title"] for m in self.store.list_meetings("quarterly", archived=True)], ["Put away"])
        self.assertTrue(self.store.load(put_away.id).archived)
        self.assertEqual(len(self.txt_files()), 2)  # nothing was deleted
        put_away.set_archived(False)
        self.store.save(put_away)
        self.assertEqual(len(self.store.list_meetings()), 2)

    def test_notes_are_saved_as_the_words_alone(self):
        session = self.store.create()
        session.add_text(5, 6, "Add an undo button.", "You")
        session.add_text(20, 21, "Make it prominent.", "You")
        self.store.save(session)
        self.assertIn("[00:00:05]  You: Add an undo button.", (self.store.folder / self.txt_files()[0]).read_text())
        session.set_kind("notes")
        path = self.store.save(session)
        text = path.read_text()
        self.assertTrue(text.endswith("Add an undo button.\n\nMake it prominent.\n"))
        self.assertNotIn("00:00:05", text)
        self.assertNotIn("You:", text)
        self.assertTrue(path.name.endswith("Notes.txt"))
        self.assertEqual(len(self.txt_files()), 1)  # renamed, not duplicated
        self.assertEqual(self.store.load(session.id).kind, "notes")
        self.assertEqual(self.store.list_meetings()[0]["kind"], "notes")
        with self.assertRaises(ValueError):
            session.set_kind("diary")

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

    def test_naming_one_paragraphs_speaker(self):
        s = self.session
        block = s.add_text(0.0, 2.0, "Hi.", "Others")
        s.set_speaker(block.id, "  Priya   Okonkwo ")
        self.assertEqual(block.speaker, "Priya Okonkwo")
        self.assertEqual(block.text, "Hi.")
        s.set_speaker(block.id, "   ")
        self.assertIsNone(block.speaker)
        # Naming one paragraph doesn't relabel speech still to come.
        self.assertEqual(s.add_text(2.2, 3.0, "More.", "Others").speaker, "Others")

    def test_renaming_a_speaker_everywhere_names_later_speech_too(self):
        s = self.session
        s.add_text(0.0, 2.0, "Hi.", "Others")
        s.add_text(2.2, 3.0, "Hello.", "You")
        s.add_text(3.2, 4.0, "How are you?", "Others")
        changed = s.rename_speaker("Others", "Priya")
        self.assertEqual([b.text for b in changed], ["Hi.", "How are you?"])
        self.assertEqual([b.speaker for b in s.blocks], ["Priya", "You", "Priya"])
        # Their next words continue the paragraph, under the new name.
        s.add_text(4.2, 5.0, "Good.", "Others")
        self.assertEqual(len(s.blocks), 3)
        self.assertEqual(s.blocks[-1].text, "How are you? Good.")
        # Renaming the new name again follows through to later speech.
        s.rename_speaker("Priya", "Priya O.")
        s.add_text(20.0, 21.0, "Bye.", "Others")
        self.assertEqual(s.blocks[-1].speaker, "Priya O.")
        self.assertEqual(s.add_text(30.0, 31.0, "Bye!", "You").speaker, "You")

    def test_speaker_names_are_saved(self):
        store = SessionStore(Path(self._tmp.name))
        s = store.create()
        s.add_text(0.0, 2.0, "Hi.", "Others")
        s.rename_speaker("Others", "Priya")
        store.save(s)
        loaded = store.load(s.id)
        self.assertEqual(loaded.blocks[0].speaker, "Priya")
        self.assertEqual(loaded.speaker_names, {"Others": "Priya"})
        self.assertIn("Priya: Hi.", (store.folder / s.txt_name).read_text())


if __name__ == "__main__":
    unittest.main()
