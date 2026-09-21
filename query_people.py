#!/usr/bin/env python3
"""Query FAIRmat Outreach Oasis Person entries and export names and emails."""

from __future__ import annotations

import argparse
import csv
import getpass
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Iterator
from datetime import date


DEFAULT_API_URL = (
    "https://fairmat-oasis.physik.hu-berlin.de/nomad-oasis/api/v1"
)
PERSON_DEFINITION = "fairmat_members.schema_packages.schema_package.Person"
AREA_FIELD = (
    "data.fairmat_roles.area#"
    "fairmat_members.schema_packages.schema_package.Person:any"
)
TASK_FIELD = (
    "data.fairmat_roles.task#"
    "fairmat_members.schema_packages.schema_package.Person:any"
)

AREAS = {
    "A": "Area A - Synthesis",
    "B": "Area B - Experiment",
    "C": "Area C - Computation",
    "D": "Area D - Data modeling and interoperability",
    "E": "Area E - Digital infrastructure",
    "F": "Area F - Enabling data-driven science",
    "G": "Area G - Outreach",
    "H": "Area H - Management",
}

TASKS = {
    "A": [
        ("A1", "Synthesis Methods"),
        ("A2", "Processing"),
        ("A3", "Functional Materials"),
    ],
    "B": [
        ("B1", "Hyperspectral Imaging"),
        ("B2", "Basic Characterization"),
        ("B3", "Time-resolved Experiments"),
        ("B4", "Multi-technique Experiments"),
    ],
    "C": [
        ("C1", "Ground-state and Electronic Structure"),
        ("C2", "Multi-excitations and Dynamics"),
        ("C3", "Multiscale Modeling"),
    ],
    "D": [
        ("D1", "Data Models and Standards"),
        ("D2", "Data Quality and Curation"),
        ("D3", "Workflows"),
    ],
    "E": [
        ("E1", "Infrastructure Operation and Maintenance"),
        ("E2", "Data Federation and Integration"),
        ("E3", "Experiment Control and Automation"),
        ("E4", "AI-ready Infrastructure"),
    ],
    "F": [
        ("F1", "Data Exploration and Integration"),
        ("F2", "Machine Learning for Characterization and Laboratory Analysis"),
        ("F3", "Benchmarking and Community Challenges"),
    ],
    "G": [
        ("G1", "Community Engagement"),
        ("G2", "Training"),
        ("G3", "Interconnectivity"),
    ],
    "H": [],
}


def request_json(
    url: str,
    payload: dict[str, Any],
    token: str | None = None,
    content_type: str = "application/json",
) -> dict[str, Any]:
    if content_type == "application/json":
        body = json.dumps(payload).encode("utf-8")
    else:
        body = urllib.parse.urlencode(payload).encode("utf-8")
    headers = {"Accept": "application/json", "Content-Type": content_type}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(url, data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            return json.load(response)
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")
        if error.code == 401:
            detail += (
                " Set NOMAD_TOKEN, or pass --username and enter your NOMAD password."
            )
        raise RuntimeError(f"Oasis returned HTTP {error.code}: {detail}") from error
    except urllib.error.URLError as error:
        raise RuntimeError(f"Could not reach {url}: {error.reason}") from error


def get_access_token(api_url: str, username: str, password: str) -> str:
    response = request_json(
        f"{api_url}/auth/token",
        {"grant_type": "password", "username": username, "password": password},
        content_type="application/x-www-form-urlencoded",
    )
    try:
        return response["access_token"]
    except KeyError as error:
        raise RuntimeError("Authentication response contained no access_token") from error


def prompt_username() -> str:
    while True:
        try:
            username = input("Your NOMAD username: ").strip()
        except EOFError as error:
            raise RuntimeError("Username input requires an interactive terminal") from error
        if username:
            return username
        print("Username cannot be empty.")


def walk_dicts(value: Any) -> Iterator[dict[str, Any]]:
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from walk_dicts(child)
    elif isinstance(value, list):
        for child in value:
            yield from walk_dicts(child)


def text_value(mapping: dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = mapping.get(key)
        if value is not None and not isinstance(value, (dict, list)):
            text = str(value).strip()
            if text:
                return text
    return ""


def extract_people(value: Any) -> Iterator[tuple[str, str]]:
    """Find schema sections containing an email and a usable name."""
    for item in walk_dicts(value):
        email = text_value(item, "email", "email_address", "e_mail")
        if not email:
            continue
        name = text_value(item, "name", "full_name", "display_name")
        if not name:
            first = text_value(item, "first_name", "given_name", "firstname")
            last = text_value(item, "last_name", "family_name", "lastname", "surname")
            name = " ".join(part for part in (first, last) if part)
        yield name, email


def load_query(path: Path) -> dict[str, Any]:
    try:
        with path.open(encoding="utf-8") as file:
            payload = json.load(file)
    except (OSError, json.JSONDecodeError) as error:
        raise RuntimeError(f"Could not load query file {path}: {error}") from error
    if not isinstance(payload, dict) or "query" not in payload:
        raise RuntimeError(f"{path} must contain a JSON object with a 'query' key")
    return payload


def choose(prompt: str, choices: list[tuple[str, str]]) -> str:
    """Display a numbered menu and return the selected choice key."""
    print(f"\n{prompt}")
    for number, (_, label) in enumerate(choices, start=1):
        print(f"  {number}. {label}")
    while True:
        try:
            answer = input(f"Select 1-{len(choices)}: ").strip()
        except EOFError as error:
            raise RuntimeError("Interactive selection requires a terminal") from error
        if answer.isdigit() and 1 <= int(answer) <= len(choices):
            return choices[int(answer) - 1][0]
        print("Please enter one of the listed numbers.")


def select_area_and_task() -> tuple[str, tuple[str, str] | None]:
    area_choices = [("ALL", "All areas")]
    area_choices.extend((letter, name) for letter, name in AREAS.items())
    area = choose("Select an Area:", area_choices)
    if area == "ALL":
        print("\nTask: All tasks (all Areas selected)")
        return area, None

    task_choices = [("ALL", f"All tasks in Area {area}")]
    task_choices.extend((code, f"Task {code} - {name}") for code, name in TASKS[area])
    task_code = choose(f"Select a task for Area {area}:", task_choices)
    if task_code == "ALL":
        return area, None
    return area, next(task for task in TASKS[area] if task[0] == task_code)


def build_query(area: str, task: tuple[str, str] | None) -> dict[str, Any]:
    filters: dict[str, Any] = {}
    if area != "ALL":
        filters[AREA_FIELD] = [AREAS[area]]
    if task:
        code, name = task
        filters[TASK_FIELD] = [f"Task {code} – {name}"]

    conditions: list[dict[str, Any]] = []
    if filters:
        conditions.append(filters)
    conditions.append(
        {"section_defs.definition_qualified_name:all": [PERSON_DEFINITION]}
    )
    return {"owner": "visible", "query": {"and": conditions}}


def safe_filename_part(value: str) -> str:
    value = re.sub(r"[^A-Za-z0-9]+", "_", value.strip())
    return value.strip("_")


def default_output_path(area: str, task: tuple[str, str] | None) -> Path:
    area_part = area.title() if area == "ALL" else area
    if task:
        code, name = task
        task_part = f"Task{code}-{safe_filename_part(name)}"
    else:
        task_part = "TaskAll"
    filename = f"Area_{area_part}_{task_part}_{date.today().isoformat()}.csv"
    return Path("data") / filename


def query_people(
    api_url: str,
    query_payload: dict[str, Any],
    token: str | None,
    page_size: int,
) -> tuple[list[tuple[str, str]], int]:
    endpoint = f"{api_url}/entries/archive/query"
    request_payload = dict(query_payload)
    request_payload["pagination"] = {"page_size": page_size}
    request_payload["required"] = {"data": "*"}
    people: set[tuple[str, str]] = set()
    entry_count = 0

    while True:
        response = request_json(endpoint, request_payload, token)
        entries = response.get("data", [])
        if not isinstance(entries, list):
            raise RuntimeError("Unexpected Oasis response: 'data' is not a list")
        entry_count += len(entries)
        for entry in entries:
            people.update(extract_people(entry))

        pagination = response.get("pagination", {})
        after = pagination.get("next_page_after_value")
        if not after:
            break
        request_payload["pagination"]["page_after_value"] = after

    return sorted(people, key=lambda person: (person[0].casefold(), person[1].casefold())), entry_count


def write_csv(rows: list[tuple[str, str]], output: Path | None) -> None:
    if output:
        output.parent.mkdir(parents=True, exist_ok=True)
    stream = output.open("w", encoding="utf-8-sig", newline="") if output else sys.stdout
    try:
        writer = csv.writer(stream)
        writer.writerow(["name", "email"])
        writer.writerows(rows)
    finally:
        if output:
            stream.close()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api-url", default=os.getenv("NOMAD_API_URL", DEFAULT_API_URL))
    parser.add_argument(
        "--query",
        type=Path,
        help="saved query JSON; when omitted, show the Area/task menus",
    )
    parser.add_argument(
        "--output", "-o", type=Path, help="CSV path; defaults to a selection-based name"
    )
    parser.add_argument("--page-size", type=int, default=100)
    parser.add_argument("--token", default=os.getenv("NOMAD_TOKEN"))
    parser.add_argument("--username", default=os.getenv("NOMAD_USERNAME"))
    parser.add_argument(
        "--password-env",
        default="NOMAD_PASSWORD",
        help="environment variable holding the password (default: NOMAD_PASSWORD)",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.page_size < 1:
        print("error: --page-size must be positive", file=sys.stderr)
        return 2
    try:
        if args.query:
            query_payload = load_query(args.query)
            output = args.output or Path(
                "data", f"Oasis_custom_query_{date.today().isoformat()}.csv"
            )
        else:
            area, task = select_area_and_task()
            query_payload = build_query(area, task)
            output = args.output or default_output_path(area, task)

        api_url = args.api_url.rstrip("/")
        token = args.token
        if not token:
            username = args.username or prompt_username()
            password = os.getenv(args.password_env) or getpass.getpass("Your NOMAD password: ")
            token = get_access_token(api_url, username, password)

        rows, entry_count = query_people(
            api_url, query_payload, token, args.page_size
        )
        write_csv(rows, output)
    except RuntimeError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1

    print(
        f"Found {len(rows)} unique people in {entry_count} matching entries; wrote {output}.",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
