import unittest

from atlas_local.text_normalization import MojibakeRepairStream, repair_mojibake_text


class TextNormalizationTests(unittest.TestCase):
    def test_repairs_common_smart_quote_mojibake(self) -> None:
        self.assertEqual(
            repair_mojibake_text("The Odyssey\u00e2\u20ac\u2122s Echo"),
            "The Odyssey\u2019s Echo",
        )

    def test_repairs_common_nonbreaking_hyphen_mojibake(self) -> None:
        self.assertEqual(
            repair_mojibake_text("Kepler\u00e2\u20ac\u2018442"),
            "Kepler\u2011442",
        )

    def test_stream_buffers_incomplete_mojibake_sequence(self) -> None:
        stream = MojibakeRepairStream()

        self.assertEqual(stream.consume("The Odyssey\u00e2"), "The Odyssey")
        self.assertEqual(stream.consume("\u20ac\u2122s Echo"), "\u2019s Echo")
        self.assertEqual(stream.flush(), "")

    def test_stream_repairs_split_double_quotes(self) -> None:
        stream = MojibakeRepairStream()

        self.assertEqual(stream.consume("She said, \u00e2\u20ac"), "She said, ")
        self.assertEqual(stream.consume("\u0153Proceed.\u00e2\u20ac"), "\u201cProceed.")
        self.assertEqual(stream.consume("\u009d"), "\u201d")


if __name__ == "__main__":
    unittest.main()
