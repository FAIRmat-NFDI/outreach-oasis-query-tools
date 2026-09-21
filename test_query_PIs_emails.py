import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch

import query_PIs_emails


class ExtractPeopleTests(unittest.TestCase):
    def test_extracts_supported_name_shapes_and_deduplicates_later(self):
        archive = {
            "data": {
                "members": [
                    {"name": "Ada Lovelace", "email": "ada@example.org"},
                    {
                        "first_name": "Grace",
                        "last_name": "Hopper",
                        "email_address": "grace@example.org",
                    },
                ]
            }
        }
        self.assertEqual(
            list(query_PIs_emails.extract_people(archive)),
            [
                ("Ada Lovelace", "ada@example.org"),
                ("Grace Hopper", "grace@example.org"),
            ],
        )


class PaginationTests(unittest.TestCase):
    @patch("query_PIs_emails.request_json")
    def test_paginates_and_deduplicates(self, request_json):
        request_json.side_effect = [
            {
                "data": [{"archive": {"data": {"name": "A", "email": "a@x"}}}],
                "pagination": {"next_page_after_value": "cursor"},
            },
            {
                "data": [{"archive": {"data": {"name": "A", "email": "a@x"}}}],
                "pagination": {},
            },
        ]
        people, count = query_PIs_emails.query_people(
            "https://example.test/api/v1", {"owner": "visible", "query": {}}, None, 10
        )
        self.assertEqual(people, [("A", "a@x")])
        self.assertEqual(count, 2)
        second_payload = request_json.call_args_list[1].args[1]
        self.assertEqual(second_payload["pagination"]["page_after_value"], "cursor")
        self.assertEqual(second_payload["required"], {"data": "*"})


class SelectionQueryTests(unittest.TestCase):
    def test_area_and_task_query(self):
        payload = query_PIs_emails.build_query(
            "B", ("B1", "Hyperspectral Imaging")
        )
        filters = payload["query"]["and"][0]
        self.assertEqual(filters[query_PIs_emails.AREA_FIELD], ["Area B - Experiment"])
        self.assertEqual(
            filters[query_PIs_emails.TASK_FIELD],
            ["Task B1 – Hyperspectral Imaging"],
        )

    def test_all_areas_has_only_person_definition_filter(self):
        payload = query_PIs_emails.build_query("ALL", None)
        self.assertEqual(
            payload["query"]["and"],
            [{"section_defs.definition_qualified_name:all": [query_PIs_emails.PERSON_DEFINITION]}],
        )

    def test_generated_filename(self):
        output = query_PIs_emails.default_output_path(
            "B", ("B1", "Hyperspectral Imaging")
        )
        self.assertEqual(
            str(output),
            str(
                Path("data")
                / f"Area_B_TaskB1-Hyperspectral_Imaging_{date.today().isoformat()}.csv"
            ),
        )


if __name__ == "__main__":
    unittest.main()
