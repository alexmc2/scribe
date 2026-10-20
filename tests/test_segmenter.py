"""The segmenter with stand-ins for the model and speech detector.

Test audio is built so the stand-ins can "hear" it: speech is a constant 0.5
signal and silence is 0, and the fake transcriber names each stretch of speech
by its position, so the tests can check exactly which audio was committed.
"""

import unittest

import numpy as np

from scribe.audio import FRAME_SAMPLES, SAMPLE_RATE
from scribe.segmenter import Segmenter, SegmenterOptions
from scribe.transcriber import Segment


def detect(audio):
    regions, start = [], None
    for i in range(0, len(audio), FRAME_SAMPLES):
        loud = audio[i : i + FRAME_SAMPLES].max() > 0.1
        if loud and start is None:
            start = i
        elif not loud and start is not None:
            regions.append((start, i))
            start = None
    if start is not None:
        regions.append((start, len(audio)))
    return regions


class FakeModel:
    def __init__(self):
        self.calls = []

    def __call__(self, audio, prompt="", final=True, timestamps=False):
        self.calls.append((len(audio), final, timestamps))
        regions = detect(audio)
        words = [f"speech{len(self.calls)}x{(e - s) // FRAME_SAMPLES}" for s, e in regions]
        if timestamps:
            return [Segment(s / SAMPLE_RATE, e / SAMPLE_RATE, w) for (s, e), w in zip(regions, words)]
        return [Segment(0, len(audio) / SAMPLE_RATE, " ".join(words))] if words else []


def tone(seconds):
    return np.full(int(seconds * SAMPLE_RATE), 0.5, dtype=np.float32)


def silence(seconds):
    return np.zeros(int(seconds * SAMPLE_RATE), dtype=np.float32)


def run(segmenter, audio, energy=None):
    """Feed audio a frame at a time, the way it arrives live, and collect commits."""
    commits, now = [], 0.0
    energy = energy if energy is not None else np.zeros((len(audio) // FRAME_SAMPLES, 1), np.float32)
    for f in range(len(audio) // FRAME_SAMPLES):
        segmenter.feed(audio[f * FRAME_SAMPLES : (f + 1) * FRAME_SAMPLES], energy[f : f + 1])
        now += 0.1
        new, _preview = segmenter.step(now)
        commits += new
    return commits


class SegmenterTest(unittest.TestCase):
    def setUp(self):
        self.model = FakeModel()
        self.segmenter = Segmenter(self.model, detect, SegmenterOptions())

    def test_a_pause_commits_the_phrase_with_its_timing(self):
        audio = np.concatenate([silence(1.0), tone(2.0), silence(1.5)])
        commits = run(self.segmenter, audio)
        self.assertEqual(len(commits), 1)
        self.assertAlmostEqual(commits[0].start, 1.0, places=1)
        self.assertAlmostEqual(commits[0].end, 3.0, places=1)
        self.assertTrue(self.model.calls[-1][1], "the commit should use the careful (final) pass")

    def test_two_phrases_give_two_commits(self):
        audio = np.concatenate([tone(1.5), silence(1.0), tone(1.0), silence(1.0)])
        commits = run(self.segmenter, audio)
        self.assertEqual(len(commits), 2)
        self.assertAlmostEqual(commits[1].start, 2.5, places=1)

    def test_silence_alone_commits_nothing_and_stays_small(self):
        commits = run(self.segmenter, silence(30.0))
        self.assertEqual(commits, [])
        self.assertLessEqual(self.segmenter.buffered_seconds, 1.0)
        self.assertEqual([c for c in self.model.calls], [], "silence shouldn't reach the model")

    def test_long_speech_is_cut_at_a_short_gap(self):
        # Gaps shorter than the commit pause, so only the length limit can split this.
        pieces = []
        for _ in range(6):
            pieces += [tone(4.0), silence(0.3)]
        commits = run(self.segmenter, np.concatenate(pieces + [silence(1.0)]))
        self.assertGreaterEqual(len(commits), 2)
        self.assertTrue(all(c.end - c.start <= 20.5 for c in commits))
        # Nothing lost: the committed spans cover all 24 s of speech.
        covered = sum(c.end - c.start for c in commits)
        self.assertGreater(covered, 23.0)

    def test_continuous_speech_uses_whisper_segments(self):
        commits = run(self.segmenter, np.concatenate([tone(25.0), silence(1.0)]))
        self.assertGreaterEqual(len(commits), 1)
        self.assertTrue(any(timestamps for _, _, timestamps in self.model.calls))

    def test_flush_commits_unfinished_speech(self):
        run(self.segmenter, tone(2.0))
        commits = self.segmenter.flush()
        self.assertEqual(len(commits), 1)
        self.assertEqual(self.segmenter.buffered_seconds, 0)

    def test_preview_appears_while_talking(self):
        audio = tone(2.0)
        previews = []
        for f in range(len(audio) // FRAME_SAMPLES):
            self.segmenter.feed(audio[f * FRAME_SAMPLES : (f + 1) * FRAME_SAMPLES], np.zeros((1, 1), np.float32))
            _, preview = self.segmenter.step(f * 0.1)
            if preview:
                previews.append(preview)
        self.assertTrue(previews)
        self.assertFalse(any(final for _, final, _ in self.model.calls), "previews use the fast pass")

    def test_speaker_comes_from_the_louder_input(self):
        segmenter = Segmenter(self.model, detect, SegmenterOptions(), speakers=["You", "Others"])
        audio = np.concatenate([tone(1.0), silence(1.0), tone(1.0), silence(1.0)])
        frames = len(audio) // FRAME_SAMPLES
        energy = np.zeros((frames, 2), np.float32)
        energy[:10, 0] = 0.2  # first phrase: microphone
        energy[20:30, 1] = 0.2  # second phrase: computer audio
        commits = run(segmenter, audio, energy)
        self.assertEqual([c.speaker for c in commits], ["You", "Others"])


if __name__ == "__main__":
    unittest.main()
