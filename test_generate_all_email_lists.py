import unittest

import generate_all_email_lists as batch


class NameMatchingTests(unittest.TestCase):
    def test_normalization_handles_accents_and_punctuation(self):
        self.assertEqual(
            batch.normalized_name("Éxample O'Person"),
            batch.normalized_name("Example O Person"),
        )

    def test_reconcile_uses_explicit_proposal_aliases(self):
        aliases = {
            batch.normalized_name("E. Person"): batch.normalized_name(
                "Example Person"
            )
        }
        verified, missing, unexpected = batch.reconcile(
            [("Example Person", "person@example.org")],
            ("E. Person",),
            aliases,
        )
        self.assertEqual(verified, [("Example Person", "person@example.org")])
        self.assertEqual(missing, [])
        self.assertEqual(unexpected, [])

    def test_reconcile_does_not_guess_unlisted_people(self):
        verified, missing, unexpected = batch.reconcile(
            [("Other Person", "other@example.org")],
            ("Expected Person",),
            {},
        )
        self.assertEqual(verified, [])
        self.assertEqual(missing, ["Expected Person"])
        self.assertEqual(unexpected, [("Other Person", "other@example.org")])


class SelectionTests(unittest.TestCase):
    def test_generates_eight_area_and_twenty_three_task_selections(self):
        rosters = batch.load_rosters(batch.EXAMPLE_ROSTERS)
        values = batch.selections(rosters)
        self.assertEqual(len([value for value in values if value.kind == "area"]), 8)
        self.assertEqual(len([value for value in values if value.kind == "task"]), 23)
        self.assertEqual(len(values), 31)

    def test_discovered_deputies_are_added_to_their_area_and_task(self):
        rosters = batch.load_rosters(batch.EXAMPLE_ROSTERS)
        record = batch.PersonRecord(
            entry_id="deputy",
            name="Future Deputy",
            email="deputy@example.org",
            notes="Deputy for Example B1 Participant",
            roles=(("Participant", "Area B - Experiment", "Task B1 – Hyperspectral Imaging"),),
        )
        aliases = batch.alias_index(rosters)
        deputies, unresolved = batch.discover_deputies([record], rosters, aliases)
        self.assertEqual(unresolved, [])
        self.assertEqual(deputies[0]["represents"], "Example B1 Participant")
        values = {
            value.code: value
            for value in batch.add_deputies_to_selections(
                batch.selections(rosters), deputies
            )
        }
        self.assertIn("Future Deputy", values["B"].expected)
        self.assertIn("Future Deputy", values["B1"].expected)

    def test_unresolved_deputy_is_not_added(self):
        rosters = batch.load_rosters(batch.EXAMPLE_ROSTERS)
        record = batch.PersonRecord(
            entry_id="unknown",
            name="Unresolved Deputy",
            email="unknown@example.org",
            notes="Deputy for Unknown Person",
            roles=(("Participant", "Area B - Experiment", "Task B1 – Hyperspectral Imaging"),),
        )
        deputies, unresolved = batch.discover_deputies(
            [record], rosters, batch.alias_index(rosters)
        )
        self.assertEqual(deputies, [])
        self.assertEqual(len(unresolved), 1)
        values = {value.code: value for value in batch.selections(rosters)}
        self.assertNotIn("Unresolved Deputy", values["B"].expected)
        self.assertNotIn("Unresolved Deputy", values["B1"].expected)

    def test_malformed_deputy_assignment_is_unresolved(self):
        rosters = batch.load_rosters(batch.EXAMPLE_ROSTERS)
        record = batch.PersonRecord(
            entry_id="mismatch",
            name="Mismatched Deputy",
            email="mismatch@example.org",
            notes="Deputy for Example B1 Participant",
            roles=(
                (
                    "Participant",
                    "Area D - Data modeling and interoperability",
                    "Task B1 – Hyperspectral Imaging",
                ),
            ),
        )
        deputies, unresolved = batch.discover_deputies(
            [record], rosters, batch.alias_index(rosters)
        )
        self.assertEqual(deputies, [])
        self.assertIn("task/area mismatch", unresolved[0]["reason"])

    def test_unknown_task_code_is_unresolved_without_crashing(self):
        rosters = batch.load_rosters(batch.EXAMPLE_ROSTERS)
        record = batch.PersonRecord(
            entry_id="unknown-task",
            name="Unknown Task Deputy",
            email="unknown-task@example.org",
            notes="Deputy for Example B1 Participant",
            roles=(("Participant", "Area A - Synthesis", "Task A4 – Unknown"),),
        )
        deputies, unresolved = batch.discover_deputies(
            [record], rosters, batch.alias_index(rosters)
        )
        self.assertEqual(deputies, [])
        self.assertIn("unknown task code(s): A4", unresolved[0]["reason"])

    def test_rows_are_derived_from_complete_oasis_roles(self):
        record = batch.PersonRecord(
            entry_id="person",
            name="Role Person",
            email="role@example.org",
            notes="",
            roles=(
                (
                    "Participant",
                    "Area D - Data modeling and interoperability",
                    "Task D2 – Data Quality and Curation",
                ),
            ),
        )
        rosters = batch.load_rosters(batch.EXAMPLE_ROSTERS)
        values = {value.code: value for value in batch.selections(rosters)}
        self.assertEqual(
            batch.rows_for_selection([record], values["D2"]),
            [("Role Person", "role@example.org")],
        )
        self.assertEqual(
            batch.rows_for_selection([record], values["D"]),
            [("Role Person", "role@example.org")],
        )


class CrossQueryRecoveryTests(unittest.TestCase):
    def test_recovers_unique_email_from_another_query(self):
        aliases = {}
        index = {
            batch.normalized_name("Expected Person"): {
                ("Expected Person", "person@example.org")
            }
        }
        verified, missing, recovered, ambiguous = batch.recover_from_other_queries(
            [], ["Expected Person"], index, aliases
        )
        self.assertEqual(verified, [("Expected Person", "person@example.org")])
        self.assertEqual(missing, [])
        self.assertEqual(recovered, [("Expected Person", "person@example.org")])
        self.assertEqual(ambiguous, {})

    def test_does_not_choose_between_multiple_emails(self):
        aliases = {}
        index = {
            batch.normalized_name("Expected Person"): {
                ("Expected Person", "first@example.org"),
                ("Expected Person", "second@example.org"),
            }
        }
        verified, missing, recovered, ambiguous = batch.recover_from_other_queries(
            [], ["Expected Person"], index, aliases
        )
        self.assertEqual(verified, [])
        self.assertEqual(missing, ["Expected Person"])
        self.assertEqual(recovered, [])
        self.assertIn("Expected Person", ambiguous)


class DiscrepancyAggregationTests(unittest.TestCase):
    def test_separates_oasis_only_people_from_role_mismatches(self):
        selection = batch.Selection(
            kind="task",
            code="A1",
            title="Example",
            page=1,
            expected=("Proposal Person",),
            task=("A1", "Example"),
        )
        results = [
            {
                "selection": selection,
                "unexpected": [
                    ("Proposal Person", "proposal@example.org"),
                    ("Oasis Only", "oasis@example.org"),
                ],
            }
        ]
        oasis_only, role_mismatches = batch.aggregate_discrepancies(results, {})
        self.assertEqual([row["name"] for row in oasis_only], ["Oasis Only"])
        self.assertEqual([row["name"] for row in role_mismatches], ["Proposal Person"])
        self.assertEqual(oasis_only[0]["tasks"], {"A1: Example"})

    def test_oasis_only_person_without_roles_is_still_reported(self):
        selection = batch.Selection(
            kind="area",
            code="A",
            title="Synthesis",
            page=1,
            expected=("Proposal Person",),
            task=None,
        )
        record = batch.PersonRecord(
            entry_id="unassigned",
            name="Unassigned Oasis Person",
            email="unassigned@example.org",
            notes="",
            roles=(),
        )
        oasis_only, role_mismatches = batch.aggregate_discrepancies(
            [{"selection": selection, "unexpected": []}], {}, [record]
        )
        self.assertEqual(role_mismatches, [])
        self.assertEqual([row["name"] for row in oasis_only], ["Unassigned Oasis Person"])
        self.assertEqual(oasis_only[0]["areas"], set())
        self.assertEqual(oasis_only[0]["tasks"], set())


if __name__ == "__main__":
    unittest.main()
