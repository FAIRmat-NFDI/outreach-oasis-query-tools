import argparse
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path
from unittest.mock import patch

import pi_areas


class ExtractPiRowsTests(unittest.TestCase):
    def test_extracts_each_area_and_role(self):
        archive = {
            "data": {
                "first_name": "Ada",
                "last_name": "Lovelace",
                "fairmat_roles": [
                    {"area": "Area C", "role": "Spokesperson"},
                    {"area": "Area G", "task": "Task G2 - Training"},
                ],
            }
        }
        self.assertEqual(
            list(pi_areas.extract_pi_rows(archive)),
            [
                ("Ada Lovelace", "Area C", "Spokesperson"),
                ("Ada Lovelace", "Area G", "Task G2 - Training"),
            ],
        )

    def test_supports_list_values(self):
        archive = {
            "name": "Grace Hopper",
            "fairmat_roles": {"area": ["Area E"], "roles": ["PI", "Lead"]},
        }
        self.assertEqual(
            list(pi_areas.extract_pi_rows(archive)),
            [
                ("Grace Hopper", "Area E", "PI"),
                ("Grace Hopper", "Area E", "Lead"),
            ],
        )


class QueryPiRowsTests(unittest.TestCase):
    @patch("pi_areas.request_json")
    def test_paginates_and_deduplicates(self, request_json):
        entry = {
            "archive": {
                "data": {
                    "name": "A Person",
                    "fairmat_roles": {"area": "Area A", "role": "Lead"},
                }
            }
        }
        request_json.side_effect = [
            {"data": [entry], "pagination": {"next_page_after_value": "next"}},
            {"data": [entry], "pagination": {}},
        ]

        rows, count = pi_areas.query_pi_rows("https://example.test", "token", 10)

        self.assertEqual(rows, [("A Person", "Area A", "Lead")])
        self.assertEqual(count, 2)
        second_payload = request_json.call_args_list[1].args[1]
        self.assertEqual(second_payload["pagination"]["page_after_value"], "next")


class CsvTests(unittest.TestCase):
    def test_writes_expected_columns(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "summary.csv"
            pi_areas.write_csv([("A Person", "Area A", "Lead")], output)
            self.assertEqual(
                output.read_text(encoding="utf-8-sig").splitlines(),
                ["name,area,role", "A Person,Area A,Lead"],
            )

    def test_writes_matrix_with_groups_and_leadership_marks(self):
        rows = [
            ("Ada Leader", "Area A - Synthesis", "Area Leader"),
            ("Grace Member", "Area A - Synthesis", "Participant"),
            ("Ada Leader", "Area B - Experiment", "Participant"),
        ]
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "diagram.svg"
            pi_areas.write_membership_matrix_svg(rows, output)
            ET.parse(output)
            svg = output.read_text(encoding="utf-8")
            self.assertEqual(svg.count("Ada Leader</text>"), 1)
            self.assertIn("SEVERAL AREAS (1)", svg)
            self.assertIn("ONE AREA (1)", svg)
            self.assertIn("◆</text>", svg)
            self.assertIn("●</text>", svg)


class AuthenticationTests(unittest.TestCase):
    @patch("pi_areas.write_csv")
    @patch("pi_areas.write_membership_matrix_svg")
    @patch("pi_areas.query_pi_rows", return_value=([], 0))
    @patch("pi_areas.get_access_token", return_value="new-token")
    @patch("pi_areas.getpass.getpass", return_value="secret")
    @patch("pi_areas.prompt_username", return_value="ada")
    @patch("pi_areas.parse_args")
    def test_prompts_for_credentials_when_token_is_missing(
        self,
        parse_args,
        prompt_username,
        password_prompt,
        get_access_token,
        query_pi_rows,
        write_membership_matrix_svg,
        write_csv,
    ):
        parse_args.return_value = argparse.Namespace(
            api_url="https://example.test/api/v1",
            output=Path("summary.csv"),
            diagram=None,
            page_size=100,
            token=None,
            username=None,
            password_env="TEST_NOMAD_PASSWORD_THAT_IS_NOT_SET",
        )

        self.assertEqual(pi_areas.main(), 0)
        prompt_username.assert_called_once_with()
        password_prompt.assert_called_once_with("Your NOMAD password: ")
        get_access_token.assert_called_once_with(
            "https://example.test/api/v1", "ada", "secret"
        )


if __name__ == "__main__":
    unittest.main()
