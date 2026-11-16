import unittest

from scribe.tidy import names_in, tidy_speech


class TidySpeechTest(unittest.TestCase):
    def test_fillers_go_and_sentences_still_start_with_a_capital(self):
        self.assertEqual(tidy_speech("I made this. Um, it runs on desktop."), "I made this. It runs on desktop.")
        self.assertEqual(tidy_speech("Uh... Erm... So, umm, what now?"), "So, what now?")
        self.assertEqual(tidy_speech("Um..."), "")

    def test_commas_around_a_filler_are_tidied(self):
        self.assertEqual(tidy_speech("I need to do, um, by Friday."), "I need to do, by Friday.")
        self.assertEqual(tidy_speech("Look back and, uh... see progress."), "Look back and see progress.")
        self.assertEqual(tidy_speech("Finish this um."), "Finish this.")

    def test_words_that_mean_something_stay(self):
        text = "Hmm, mm-hmm, uh-huh. Error, user, umbrella, her."
        self.assertEqual(tidy_speech(text), text)

    def test_stutters_across_a_pause_collapse(self):
        self.assertEqual(tidy_speech("It's... It's okay."), "It's okay.")
        self.assertEqual(tidy_speech("And how... How these... How these look."), "And how these look.")
        # Deliberate repetition, with no pause between, is left alone.
        self.assertEqual(tidy_speech("It was very, very good."), "It was very, very good.")

    def test_pauses_mid_sentence_are_joined_up(self):
        self.assertEqual(tidy_speech("It will... motivate me."), "It will motivate me.")
        self.assertEqual(
            tidy_speech("I'm not feeling... Particularly excited... About... Using... This."),
            "I'm not feeling particularly excited about using this.",
        )
        self.assertEqual(tidy_speech("The... Problem is simple."), "The problem is simple.")
        self.assertEqual(tidy_speech("Not just... A day."), "Not just a day.")

    def test_names_acronyms_and_new_thoughts_keep_their_pause(self):
        self.assertEqual(tidy_speech("I spoke to... Veronica."), "I spoke to... Veronica.")
        self.assertEqual(tidy_speech("Ask the... OKR owners."), "Ask the... OKR owners.")
        self.assertEqual(tidy_speech("I think... I don't know."), "I think... I don't know.")
        names = names_in("Priya, Okonkwo, Kubernetes")
        self.assertEqual(tidy_speech("Deploy the... Kubernetes cluster.", names), "Deploy the... Kubernetes cluster.")


if __name__ == "__main__":
    unittest.main()
