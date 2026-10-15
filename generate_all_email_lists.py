#!/usr/bin/env python3
"""Generate proposal-verified Apple Mail recipient lists for every area and task."""

from __future__ import annotations

import argparse
import csv
import getpass
import json
import os
import re
import sys
import unicodedata
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

import query_PIs_emails as oasis


HERE = Path(__file__).resolve().parent
DEFAULT_ROSTERS = HERE / "proposal_rosters.json"
EXAMPLE_ROSTERS = HERE / "proposal_rosters.example.json"
TASK_TITLES = {
    code: title for area_tasks in oasis.TASKS.values() for code, title in area_tasks
}


@dataclass(frozen=True)
class Selection:
    kind: str
    code: str
    title: str
    page: int
    expected: tuple[str, ...]
    task: tuple[str, str] | None


@dataclass(frozen=True)
class PersonRecord:
    entry_id: str
    name: str
    email: str
    notes: str
    roles: tuple[tuple[str, str, str], ...]


def normalized_name(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", value)
    without_marks = "".join(char for char in decomposed if not unicodedata.combining(char))
    return re.sub(r"[^a-z0-9]+", "", without_marks.casefold())


def load_rosters(path: Path) -> dict[str, Any]:
    try:
        with path.open(encoding="utf-8") as stream:
            value = json.load(stream)
    except (OSError, json.JSONDecodeError) as error:
        raise RuntimeError(f"Could not load proposal rosters from {path}: {error}") from error
    if (
        not isinstance(value, dict)
        or not isinstance(value.get("areas"), dict)
        or not isinstance(value.get("tasks"), dict)
    ):
        raise RuntimeError(f"Invalid proposal roster structure in {path}")
    return value


def proposal_names_for_task(task: dict[str, Any]) -> tuple[str, ...]:
    return tuple(dict.fromkeys([task["leader"], *task["participants"]]))


def selections(rosters: dict[str, Any]) -> list[Selection]:
    result: list[Selection] = []
    tasks = rosters["tasks"]
    for area_code, area_title in oasis.AREAS.items():
        area = rosters["areas"][area_code]
        expected: list[str] = list(area["leaders"])
        for task_code, _task_title in oasis.TASKS[area_code]:
            expected.extend(proposal_names_for_task(tasks[task_code]))
        result.append(
            Selection(
                kind="area",
                code=area_code,
                title=area_title.split(" - ", 1)[-1],
                page=int(area["page"]),
                expected=tuple(dict.fromkeys(expected)),
                task=None,
            )
        )
        for task_code, oasis_task_title in oasis.TASKS[area_code]:
            task = tasks[task_code]
            result.append(
                Selection(
                    kind="task",
                    code=task_code,
                    title=str(task["title"]),
                    page=int(task["page"]),
                    expected=proposal_names_for_task(task),
                    task=(task_code, oasis_task_title),
                )
            )
    return result


def alias_index(rosters: dict[str, Any]) -> dict[str, str]:
    aliases = rosters.get("aliases", {})
    return {normalized_name(source): normalized_name(target) for source, target in aliases.items()}


def canonical_name(name: str, aliases: dict[str, str]) -> str:
    normalized = normalized_name(name)
    return aliases.get(normalized, normalized)


def person_record(entry: dict[str, Any]) -> PersonRecord | None:
    archive = entry.get("archive", {})
    data = archive.get("data", {}) if isinstance(archive, dict) else {}
    if not isinstance(data, dict):
        return None
    email = oasis.text_value(data, "email", "email_address", "e_mail")
    if not email:
        return None
    name = oasis.text_value(data, "name", "full_name", "display_name")
    if not name:
        first = oasis.text_value(data, "first_name", "given_name", "firstname")
        last = oasis.text_value(data, "last_name", "family_name", "lastname", "surname")
        name = " ".join(part for part in (first, last) if part)
    if not name:
        return None
    roles: list[tuple[str, str, str]] = []
    fairmat_roles = data.get("fairmat_roles") or []
    if not isinstance(fairmat_roles, list):
        fairmat_roles = []
    for role in fairmat_roles:
        if isinstance(role, dict):
            roles.append(
                (
                    oasis.text_value(role, "role"),
                    oasis.text_value(role, "area"),
                    oasis.text_value(role, "task"),
                )
            )
    return PersonRecord(
        entry_id=str(entry.get("entry_id") or f"{name}\0{email}"),
        name=name,
        email=email,
        notes=oasis.text_value(data, "notes"),
        roles=tuple(roles),
    )


def query_person_records(
    api_url: str, token: str, page_size: int
) -> tuple[list[PersonRecord], int]:
    """Query all PIs once and retain complete records for local role routing."""
    endpoint = f"{api_url}/entries/archive/query"
    records: dict[str, PersonRecord] = {}
    request_payload = oasis.build_query("ALL", None)
    request_payload["pagination"] = {"page_size": page_size}
    request_payload["required"] = {"data": "*"}
    entry_count = 0
    while True:
        response = oasis.request_json(endpoint, request_payload, token)
        entries = response.get("data", [])
        if not isinstance(entries, list):
            raise RuntimeError("Unexpected Oasis response: 'data' is not a list")
        entry_count += len(entries)
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            record = person_record(entry)
            if record:
                records[record.entry_id] = record
        after = response.get("pagination", {}).get("next_page_after_value")
        if not after:
            break
        request_payload["pagination"]["page_after_value"] = after
    return sorted(records.values(), key=lambda row: row.name.casefold()), entry_count


def record_role_codes(record: PersonRecord) -> tuple[set[str], set[str]]:
    areas: set[str] = set()
    tasks: set[str] = set()
    for _role, area, task in record.roles:
        area_match = re.search(r"\bArea\s+([A-H])\b", area)
        task_match = re.search(r"\bTask\s+([A-H][1-4])\b", task)
        if area_match:
            areas.add(area_match.group(1))
        if task_match:
            task_code = task_match.group(1)
            if task_code in TASK_TITLES:
                tasks.add(task_code)
                areas.add(task_code[0])
    return areas, tasks


def rows_for_selection(
    records: list[PersonRecord], selection: Selection
) -> list[tuple[str, str]]:
    rows: set[tuple[str, str]] = set()
    for record in records:
        areas, tasks = record_role_codes(record)
        if (
            selection.kind == "area" and selection.code in areas
        ) or (
            selection.kind == "task" and selection.code in tasks
        ):
            rows.add((record.name, record.email))
    return sorted(rows, key=lambda row: (row[0].casefold(), row[1].casefold()))


def proposal_name_index(
    rosters: dict[str, Any], aliases: dict[str, str]
) -> dict[str, str]:
    names: list[str] = []
    for area in rosters["areas"].values():
        names.extend(area["leaders"])
    for task in rosters["tasks"].values():
        names.extend(proposal_names_for_task(task))
    return {canonical_name(name, aliases): name for name in names}


def discover_deputies(
    records: list[PersonRecord],
    rosters: dict[str, Any],
    aliases: dict[str, str],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    proposal_names = proposal_name_index(rosters, aliases)
    confirmed: list[dict[str, Any]] = []
    unresolved: list[dict[str, Any]] = []
    for record in records:
        match = re.search(r"\bDeputy\s+for\s+([^;\n]+)", record.notes, re.IGNORECASE)
        if not match:
            continue
        represented_text = match.group(1).strip().rstrip(".")
        represented = proposal_names.get(canonical_name(represented_text, aliases))
        areas, tasks = record_role_codes(record)
        reasons: list[str] = []
        if not represented:
            reasons.append(f"represented PI `{represented_text}` is not in the proposal roster")
        if not areas:
            reasons.append("no valid Area A-H assignment in fairmat_roles")
        if not tasks:
            reasons.append("no valid Task A1-G3 assignment in fairmat_roles")
        invalid_pairs: list[str] = []
        invalid_task_codes: list[str] = []
        for _role, area, task in record.roles:
            area_match = re.search(r"\bArea\s+([A-H])\b", area)
            task_match = re.search(r"\bTask\s+([A-H][1-4])\b", task)
            if task_match and task_match.group(1) not in TASK_TITLES:
                invalid_task_codes.append(task_match.group(1))
            elif area_match and task_match and task_match.group(1)[0] != area_match.group(1):
                invalid_pairs.append(
                    f"Area {area_match.group(1)}/Task {task_match.group(1)}"
                )
        if invalid_task_codes:
            reasons.append("unknown task code(s): " + ", ".join(invalid_task_codes))
        if invalid_pairs:
            reasons.append("task/area mismatch for " + ", ".join(invalid_pairs))
        value: dict[str, Any] = {
            "name": record.name,
            "email": record.email,
            "represents": represented or represented_text,
            "area_codes": areas,
            "task_codes": tasks,
            "areas": {f"{code}: {oasis.AREAS[code].split(' - ', 1)[-1]}" for code in areas},
            "tasks": {
                f"{code}: {TASK_TITLES[code]}"
                for code in tasks
            },
            "source": "Oasis Person.notes and fairmat_roles",
            "notes": record.notes,
        }
        if reasons:
            value["reason"] = "; ".join(reasons)
            unresolved.append(value)
        else:
            confirmed.append(value)
    key = lambda row: (row["name"].casefold(), row["email"].casefold())
    return sorted(confirmed, key=key), sorted(unresolved, key=key)


def add_deputies_to_selections(
    values: list[Selection], deputies: list[dict[str, Any]]
) -> list[Selection]:
    updated: list[Selection] = []
    for selection in values:
        expected = list(selection.expected)
        for deputy in deputies:
            codes = deputy["area_codes"] if selection.kind == "area" else deputy["task_codes"]
            if selection.code in codes:
                expected.append(deputy["name"])
        updated.append(
            Selection(
                kind=selection.kind,
                code=selection.code,
                title=selection.title,
                page=selection.page,
                expected=tuple(dict.fromkeys(expected)),
                task=selection.task,
            )
        )
    return updated


def reconcile(
    rows: list[tuple[str, str]], expected: tuple[str, ...], aliases: dict[str, str]
) -> tuple[list[tuple[str, str]], list[str], list[tuple[str, str]]]:
    expected_by_key: dict[str, list[str]] = {}
    for name in expected:
        expected_by_key.setdefault(canonical_name(name, aliases), []).append(name)

    verified: list[tuple[str, str]] = []
    unexpected: list[tuple[str, str]] = []
    matched: set[str] = set()
    for name, email in rows:
        key = canonical_name(name, aliases)
        if key in expected_by_key:
            verified.append((name, email))
            matched.add(key)
        else:
            unexpected.append((name, email))

    missing = [
        name for name in expected if canonical_name(name, aliases) not in matched
    ]
    return verified, missing, unexpected


def build_record_people_index(
    records: list[PersonRecord], aliases: dict[str, str]
) -> dict[str, set[tuple[str, str]]]:
    people: dict[str, set[tuple[str, str]]] = {}
    for record in records:
        people.setdefault(canonical_name(record.name, aliases), set()).add(
            (record.name, record.email)
        )
    return people


def recover_from_other_queries(
    verified: list[tuple[str, str]],
    missing: list[str],
    people: dict[str, set[tuple[str, str]]],
    aliases: dict[str, str],
) -> tuple[
    list[tuple[str, str]],
    list[str],
    list[tuple[str, str]],
    dict[str, list[tuple[str, str]]],
]:
    recovered: list[tuple[str, str]] = []
    unresolved: list[str] = []
    ambiguous: dict[str, list[tuple[str, str]]] = {}
    existing = set(verified)
    for expected_name in missing:
        candidates = sorted(people.get(canonical_name(expected_name, aliases), set()))
        if len(candidates) == 1:
            candidate = candidates[0]
            if candidate not in existing:
                verified.append(candidate)
                existing.add(candidate)
                recovered.append(candidate)
        elif len(candidates) > 1:
            ambiguous[expected_name] = candidates
            unresolved.append(expected_name)
        else:
            unresolved.append(expected_name)
    verified.sort(key=lambda person: (person[0].casefold(), person[1].casefold()))
    return verified, unresolved, recovered, ambiguous


def safe_part(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", value.casefold()).strip("_")


def write_recipient_file(path: Path, rows: list[tuple[str, str]]) -> None:
    recipients = ", ".join(f"{name} <{email}>" for name, email in rows)
    path.write_text(recipients + "\n", encoding="utf-8")


def write_supporting_csv(path: Path, rows: list[tuple[str, str]]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(["name", "email"])
        writer.writerows(rows)


def output_stem(selection: Selection) -> str:
    return f"{selection.kind}_{selection.code}_{safe_part(selection.title)}"


def aggregate_discrepancies(
    results: list[dict[str, Any]],
    aliases: dict[str, str],
    records: list[PersonRecord] | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    proposal_keys = {
        canonical_name(name, aliases)
        for result in results
        for name in result["selection"].expected
    }
    oasis_only: dict[tuple[str, str], dict[str, Any]] = {}
    role_mismatches: dict[tuple[str, str], dict[str, Any]] = {}
    if records is not None:
        for person in records:
            if canonical_name(person.name, aliases) in proposal_keys:
                continue
            areas, tasks = record_role_codes(person)
            oasis_only[(person.name, person.email)] = {
                "name": person.name,
                "email": person.email,
                "areas": {
                    f"{code}: {oasis.AREAS[code].split(' - ', 1)[-1]}"
                    for code in areas
                },
                "tasks": {f"{code}: {TASK_TITLES[code]}" for code in tasks},
            }
    for result in results:
        selection: Selection = result["selection"]
        for name, email in result["unexpected"]:
            is_proposal_person = canonical_name(name, aliases) in proposal_keys
            if not is_proposal_person and records is not None:
                continue
            target = role_mismatches if is_proposal_person else oasis_only
            record = target.setdefault(
                (name, email),
                {"name": name, "email": email, "areas": set(), "tasks": set()},
            )
            label = f"{selection.code}: {selection.title}"
            record[f"{selection.kind}s"].add(label)

    def ordered(values: dict[tuple[str, str], dict[str, Any]]) -> list[dict[str, Any]]:
        return sorted(
            values.values(),
            key=lambda value: (value["name"].casefold(), value["email"].casefold()),
        )

    return ordered(oasis_only), ordered(role_mismatches)


def write_oasis_only_files(output_dir: Path, rows: list[dict[str, Any]]) -> None:
    recipients = [(row["name"], row["email"]) for row in rows]
    write_recipient_file(output_dir / "oasis_only_recipients.txt", recipients)
    with (output_dir / "oasis_only_people.csv").open(
        "w", encoding="utf-8-sig", newline=""
    ) as stream:
        writer = csv.writer(stream)
        writer.writerow(["name", "email", "oasis_areas", "oasis_tasks"])
        for row in rows:
            writer.writerow(
                [
                    row["name"],
                    row["email"],
                    "; ".join(sorted(row["areas"])),
                    "; ".join(sorted(row["tasks"])),
                ]
            )


def write_deputy_files(output_dir: Path, deputies: list[dict[str, Any]]) -> None:
    write_recipient_file(
        output_dir / "pi_deputies_recipients.txt",
        [(row["name"], row["email"]) for row in deputies],
    )
    with (output_dir / "pi_deputies.csv").open(
        "w", encoding="utf-8-sig", newline=""
    ) as stream:
        writer = csv.DictWriter(
            stream,
            fieldnames=[
                "name",
                "email",
                "represents",
                "oasis_area",
                "oasis_task",
                "source",
            ],
        )
        writer.writeheader()
        for row in deputies:
            writer.writerow(
                {
                    "name": row["name"],
                    "email": row["email"],
                    "represents": row["represents"],
                    "oasis_area": "; ".join(sorted(row["areas"])),
                    "oasis_task": "; ".join(sorted(row["tasks"])),
                    "source": row["source"],
                }
            )


def write_audit(
    path: Path,
    source: str,
    results: list[dict[str, Any]],
    oasis_only: list[dict[str, Any]],
    role_mismatches: list[dict[str, Any]],
    deputies: list[dict[str, Any]],
    unresolved_deputies: list[dict[str, Any]],
) -> None:
    lines = [
        "# FAIRmat email-list audit",
        "",
        f"Generated: {date.today().isoformat()}",
        f"Proposal: `{source}`",
        "",
        (
            "The Apple Mail lists include Oasis recipients who match either the "
            "proposal roster or the confirmed PI-deputy mapping below."
        ),
        (
            "Known proposal spelling/initial variants are resolved through "
            "`proposal_rosters.json`; all other discrepancies are reported below."
        ),
        "",
        "## Confirmed PI deputies",
        "",
        (
            "Deputy links come from each Oasis Person record's `notes` field; "
            "area/task assignments come from its `fairmat_roles` field. These "
            "deputies are included in the corresponding area and task recipient "
            "lists."
        ),
        (
            f"Automatic deputy discovery: {len(deputies)} confirmed, "
            f"{len(unresolved_deputies)} unresolved."
        ),
        "",
        "| Deputy | Email | Represents | Oasis area | Oasis task |",
        "|---|---|---|---|---|",
    ]
    for deputy in deputies:
        lines.append(
            f"| {deputy['name']} | {deputy['email']} | {deputy['represents']} | "
            f"{'; '.join(sorted(deputy['areas']))} | "
            f"{'; '.join(sorted(deputy['tasks']))} |"
        )
    if unresolved_deputies:
        lines.extend(
            [
                "",
                "### Unresolved deputy candidates",
                "",
                (
                    "These Oasis records contain `Deputy for ...` notes but are "
                    "excluded until the represented PI and assignments can be "
                    "validated."
                ),
                "",
                "| Person | Notes | Oasis areas | Oasis tasks | Reason |",
                "|---|---|---|---|---|",
            ]
        )
        for deputy in unresolved_deputies:
            lines.append(
                f"| {deputy['name']} | {deputy['notes']} | "
                f"{'; '.join(sorted(deputy['areas'])) or '—'} | "
                f"{'; '.join(sorted(deputy['tasks'])) or '—'} | "
                f"{deputy['reason']} |"
            )
    lines.extend(
        [
            "",
            "## Aggregate Oasis/proposal discrepancies",
            "",
            (
                "Oasis-only people absent from the proposal and confirmed-deputy "
                f"roster: {len(oasis_only)}"
            ),
            (
                "Proposal-listed people with additional Oasis role assignments: "
                f"{len(role_mismatches)}"
            ),
            "",
        ]
    )
    if oasis_only:
        lines.extend(
            [
                "### Oasis-only people absent from the proposal",
                "",
                (
                    "These people are excluded from the proposal-verified area/task "
                    "lists. A paste-ready aggregate is in "
                    "`oasis_only_recipients.txt`; structured assignments are in "
                    "`oasis_only_people.csv`."
                ),
                "",
                "| Name | Email | Oasis areas | Oasis tasks |",
                "|---|---|---|---|",
            ]
        )
        for row in oasis_only:
            lines.append(
                f"| {row['name']} | {row['email']} | "
                f"{'; '.join(sorted(row['areas'])) or '—'} | "
                f"{'; '.join(sorted(row['tasks'])) or '—'} |"
            )
        lines.append("")
    if role_mismatches:
        lines.extend(
            [
                "### Proposal-listed people with additional Oasis assignments",
                "",
                (
                    "These people occur elsewhere in the proposal but were excluded "
                    "from the specific assignments below because the proposal does "
                    "not list them there."
                ),
                "",
                "| Name | Email | Additional Oasis areas | Additional Oasis tasks |",
                "|---|---|---|---|",
            ]
        )
        for row in role_mismatches:
            lines.append(
                f"| {row['name']} | {row['email']} | "
                f"{'; '.join(sorted(row['areas'])) or '—'} | "
                f"{'; '.join(sorted(row['tasks'])) or '—'} |"
            )
        lines.append("")
    for result in results:
        selection: Selection = result["selection"]
        lines.extend(
            [
                f"## {selection.kind.title()} {selection.code}: {selection.title}",
                "",
                f"Proposal PDF page: {selection.page}",
                f"Oasis entries matching this assignment: {result['entry_count']}",
                f"Verified recipients written: {len(result['verified'])}",
                (
                    "Expected recipients recovered from another Oasis query: "
                    f"{len(result['recovered'])}"
                ),
                f"Expected proposal/deputy names missing from Oasis: {len(result['missing'])}",
                f"Ambiguous proposal names not written: {len(result['ambiguous'])}",
                (
                    "Oasis recipients excluded as absent from this proposal/deputy "
                    f"assignment: {len(result['unexpected'])}"
                ),
                "",
            ]
        )
        if result["missing"]:
            lines.append("Missing: " + "; ".join(result["missing"]))
            lines.append("")
        if result["recovered"]:
            lines.append(
                "Recovered from other Oasis records: "
                + "; ".join(f"{name} <{email}>" for name, email in result["recovered"])
            )
            lines.append("")
        if result["ambiguous"]:
            for expected_name, candidates in result["ambiguous"].items():
                lines.append(
                    f"Ambiguous `{expected_name}`: "
                    + "; ".join(f"{name} <{email}>" for name, email in candidates)
                )
            lines.append("")
        if result["unexpected"]:
            lines.append(
                "Excluded: "
                + "; ".join(f"{name} <{email}>" for name, email in result["unexpected"])
            )
            lines.append("")
    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rosters", type=Path, default=DEFAULT_ROSTERS)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--api-url", default=os.getenv("NOMAD_API_URL", oasis.DEFAULT_API_URL))
    parser.add_argument("--token", default=os.getenv("NOMAD_TOKEN"))
    parser.add_argument("--username", default=os.getenv("NOMAD_USERNAME"))
    parser.add_argument("--password-env", default="NOMAD_PASSWORD")
    parser.add_argument("--page-size", type=int, default=20)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.page_size < 1:
        print("error: --page-size must be positive", file=sys.stderr)
        return 2
    try:
        rosters = load_rosters(args.rosters)
        expected_task_codes = {
            code for area_tasks in oasis.TASKS.values() for code, _title in area_tasks
        }
        if set(rosters["tasks"]) != expected_task_codes:
            raise RuntimeError(
                "Proposal roster task codes do not match the Oasis tool's task codes"
            )

        token = args.token
        if not token:
            username = args.username or oasis.prompt_username()
            password = os.getenv(args.password_env) or getpass.getpass("Your NOMAD password: ")
            token = oasis.get_access_token(args.api_url.rstrip("/"), username, password)

        output_dir = args.output_dir or HERE / "data" / f"email_lists_{date.today().isoformat()}"
        output_dir.mkdir(parents=True, exist_ok=True)
        aliases = alias_index(rosters)
        records, oasis_entry_count = query_person_records(
            args.api_url.rstrip("/"), token, args.page_size
        )
        print(
            f"queried Oasis once: {len(records)} unique PIs from "
            f"{oasis_entry_count} entries",
            file=sys.stderr,
        )
        deputies, unresolved_deputies = discover_deputies(records, rosters, aliases)
        selection_values = add_deputies_to_selections(selections(rosters), deputies)
        print(
            f"discovered {len(deputies)} confirmed deputies and "
            f"{len(unresolved_deputies)} unresolved deputy candidates",
            file=sys.stderr,
        )
        query_results: list[dict[str, Any]] = []
        for selection in selection_values:
            rows = rows_for_selection(records, selection)
            query_results.append(
                {"selection": selection, "entry_count": len(rows), "rows": rows}
            )

        people = build_record_people_index(records, aliases)
        results: list[dict[str, Any]] = []
        for query_result in query_results:
            selection = query_result["selection"]
            rows = query_result["rows"]
            entry_count = query_result["entry_count"]
            verified, missing, unexpected = reconcile(rows, selection.expected, aliases)
            verified, missing, recovered, ambiguous = recover_from_other_queries(
                verified, missing, people, aliases
            )
            stem = output_stem(selection)
            write_recipient_file(output_dir / f"{stem}.txt", verified)
            write_supporting_csv(output_dir / f"{stem}.csv", verified)
            results.append(
                {
                    "selection": selection,
                    "entry_count": entry_count,
                    "verified": verified,
                    "missing": missing,
                    "recovered": recovered,
                    "ambiguous": ambiguous,
                    "unexpected": unexpected,
                }
            )
            print(
                f"{selection.kind} {selection.code}: {len(verified)} verified, "
                f"{len(recovered)} recovered, {len(missing)} missing, "
                f"{len(ambiguous)} ambiguous, {len(unexpected)} excluded",
                file=sys.stderr,
            )

        oasis_only, role_mismatches = aggregate_discrepancies(
            results, aliases, records
        )
        write_oasis_only_files(output_dir, oasis_only)
        write_deputy_files(output_dir, deputies)
        write_audit(
            output_dir / "AUDIT.md",
            str(rosters["source"]),
            results,
            oasis_only,
            role_mismatches,
            deputies,
            unresolved_deputies,
        )
    except (RuntimeError, TimeoutError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1

    print(f"Wrote {len(results)} recipient lists to {output_dir}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
