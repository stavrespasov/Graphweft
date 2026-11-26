from collections import Counter
from fractions import Fraction
import hashlib
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from zipfile import ZipFile

from studies.bike_sharing import prepare


class StudyInputTests(unittest.TestCase):
    def test_replaced_source_archive_fails_before_parsing(self):
        with TemporaryDirectory() as directory:
            archive = Path(directory) / "bike-sharing.zip"
            archive.write_bytes(b"Unexpected download")
            with self.assertRaisesRegex(ValueError, "SHA-256 differs"):
                prepare.read_days(archive)

    def test_missing_hour_is_excluded_and_cutoffs_are_inclusive(self):
        rows = (
            "dteday,workingday,hr,cnt\n"
            "2020-01-01,1,8,100\n2020-01-01,1,12,99\n2020-01-01,1,18,101\n"
            "2020-01-02,0,8,90\n2020-01-02,0,18,110\n"
            "2020-01-03,0,8,90\n2020-01-03,0,12,110\n2020-01-03,0,18,90\n"
        )
        with TemporaryDirectory() as directory:
            archive = Path(directory) / "bike-sharing.zip"
            with ZipFile(archive, "w") as output:
                output.writestr("hour.csv", rows)
            digest = hashlib.sha256(archive.read_bytes()).hexdigest()
            with patch.object(prepare, "ARCHIVE_SHA256", digest):
                observed, workdays = prepare.read_days(archive)

        self.assertEqual(set(workdays) - set(observed), {"2020-01-02"})
        counts = prepare.day_counts(observed, workdays, (100, 100, 100))
        self.assertEqual(counts["source"], {(1, 0, 1): 1})
        self.assertEqual(counts["target"], {(0, 1, 0): 1})

    def test_unobserved_parent_context_cannot_add_probability_mass(self):
        self.assertEqual(prepare.chain_law(Counter({(0, 0, 0): 3, (0, 0, 1): 1})),
                         [Fraction(3, 4), Fraction(1, 4), 0, 0, 0, 0, 0, 0])
