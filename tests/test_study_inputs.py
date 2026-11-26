from collections import Counter
from datetime import date
from fractions import Fraction
import hashlib
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from zipfile import ZipFile

from studies.appliance_energy import prepare as energy
from studies.bike_sharing import prepare


class StudyInputTests(unittest.TestCase):
    def test_replaced_source_archive_fails_before_parsing(self):
        with TemporaryDirectory() as directory:
            archive = Path(directory) / "bike-sharing.zip"
            archive.write_bytes(b"Unexpected download")
            for study in (prepare, energy):
                with self.subTest(study=study.__name__), self.assertRaisesRegex(ValueError, "SHA-256 differs"):
                    study.read_days(archive)

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

    def test_appliance_energy_uses_exact_times_and_calendar_weekends(self):
        rows = (
            "date,Appliances\n"
            "2016-01-15 08:00:00,60\n2016-01-15 12:00:00,79\n2016-01-15 18:00:00,100\n"
            "2016-01-16 08:00:00,59\n2016-01-16 12:00:00,80\n2016-01-16 18:00:00,99\n"
            "2016-01-17 08:00:00,100\n2016-01-17 12:10:00,100\n2016-01-17 18:00:00,100\n"
        )
        with TemporaryDirectory() as directory:
            archive = Path(directory) / "energy.zip"
            with ZipFile(archive, "w") as output:
                output.writestr("energydata_complete.csv", rows)
            digest = hashlib.sha256(archive.read_bytes()).hexdigest()
            with patch.object(energy, "ARCHIVE_SHA256", digest):
                observed, excluded = energy.read_days(archive)

        self.assertEqual(excluded, [date(2016, 1, 17)])
        model, counts = energy.make_model(observed, (60, 80, 100))
        self.assertEqual(counts["source"], [0, 0, 0, 0, 0, 1, 0, 0])
        self.assertEqual(counts["target"], [0, 0, 1, 0, 0, 0, 0, 0])
        self.assertEqual(model["parents"]["18:00"], ["08:00", "12:00"])
