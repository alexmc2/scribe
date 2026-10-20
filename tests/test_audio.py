import unittest
from unittest import mock

from scribe import audio
from scribe.audio import DEFAULT_MIC, Source

LAPTOP = {"device.bus": "pci", "device.description": "Raptor Lake-P/U/H cAVS"}


def source(name, description, monitor, props):
    label, detail, icon = audio._friendly(description, monitor, props)
    return Source(name, description, monitor, label, detail, icon)


SOURCES = [
    source("hp.monitor", "Monitor of Studio Headphones", True,
           {"device.bus": "bluetooth", "device.form_factor": "headset", "device.description": "Studio Headphones"}),
    source("jack", "Raptor Lake-P/U/H cAVS Stereo Microphone", False,
           {**LAPTOP, "device.profile.description": "Stereo Microphone"}),
    source("dmic", "Raptor Lake-P/U/H cAVS Digital Microphone", False,
           {**LAPTOP, "device.profile.description": "Digital Microphone"}),
    source("hp.mic", "Studio Headphones", False,
           {"device.bus": "bluetooth", "device.form_factor": "headset", "device.description": "Studio Headphones"}),
]


class FriendlyNamesTest(unittest.TestCase):
    def test_laptop_devices_drop_the_chipset_name(self):
        self.assertEqual((SOURCES[2].label, SOURCES[2].detail), ("Digital Microphone", "This computer"))

    def test_bluetooth_headphones(self):
        self.assertEqual((SOURCES[3].label, SOURCES[3].detail, SOURCES[3].icon),
                         ("Studio Headphones", "Bluetooth headphones", "headset"))


class ResolveMicrophoneTest(unittest.TestCase):
    def resolve(self, default_source):
        with mock.patch.object(audio, "default_names", return_value=(default_source, "x.monitor")):
            return audio.resolve_microphone(SOURCES)

    def test_a_real_default_microphone_is_used_as_is(self):
        self.assertEqual(self.resolve("hp.mic"), DEFAULT_MIC)

    def test_a_monitor_default_falls_back_to_the_built_in_microphone(self):
        # The default input being "what you hear" must never be recorded as the microphone.
        self.assertEqual(self.resolve("hp.monitor"), "dmic")

    def test_a_missing_default_also_falls_back(self):
        self.assertEqual(self.resolve(""), "dmic")


if __name__ == "__main__":
    unittest.main()
