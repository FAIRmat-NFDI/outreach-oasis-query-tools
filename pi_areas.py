#!/usr/bin/env python3
"""Export a CSV summary of every PI's FAIRmat areas and roles."""

from __future__ import annotations

import argparse
import csv
import getpass
import html
import os
import sys
from datetime import date
from pathlib import Path
from typing import Any, Iterator

from query_PIs_emails import (
    DEFAULT_API_URL,
    MEMBER_TYPE_FIELD,
    PERSON_DEFINITION,
    get_access_token,
    prompt_username,
    request_json,
    text_value,
    walk_dicts,
)


def build_query() -> dict[str, Any]:
    """Build a query that selects every visible Person entry of type PI."""
    return {
        "owner": "visible",
        "query": {
            "and": [
                {MEMBER_TYPE_FIELD: ["PI"]},
                {
                    "section_defs.definition_qualified_name:all": [
                        PERSON_DEFINITION
                    ]
                },
            ]
        },
    }


def scalar_values(value: Any) -> list[str]:
    """Turn a scalar or a list of scalars into a clean list of strings."""
    values = value if isinstance(value, list) else [value]
    return [
        str(item).strip()
        for item in values
        if item is not None
        and not isinstance(item, (dict, list))
        and str(item).strip()
    ]


def person_name(person: dict[str, Any]) -> str:
    """Read either a full name or separate first and last names."""
    name = text_value(person, "name", "full_name", "display_name")
    if name:
        return name
    first = text_value(person, "first_name", "given_name", "firstname")
    last = text_value(person, "last_name", "family_name", "lastname", "surname")
    return " ".join(part for part in (first, last) if part)


def extract_pi_rows(value: Any) -> Iterator[tuple[str, str, str]]:
    """Yield one (name, area, role) row for each FAIRmat role assignment."""
    for person in walk_dicts(value):
        name = person_name(person)
        fairmat_roles = person.get("fairmat_roles")
        if not name or not fairmat_roles:
            continue

        role_sections = (
            fairmat_roles if isinstance(fairmat_roles, list) else [fairmat_roles]
        )
        for section in role_sections:
            if not isinstance(section, dict):
                continue

            areas = scalar_values(section.get("area")) or [""]
            roles = (
                scalar_values(section.get("role"))
                or scalar_values(section.get("roles"))
                or scalar_values(section.get("task"))
                or [""]
            )
            for area in areas:
                for role in roles:
                    yield name, area, role


def query_pi_rows(
    api_url: str,
    token: str,
    page_size: int,
) -> tuple[list[tuple[str, str, str]], int]:
    """Fetch every result page and return sorted, duplicate-free CSV rows."""
    endpoint = f"{api_url}/entries/archive/query"
    payload = build_query()
    payload["pagination"] = {"page_size": page_size}
    payload["required"] = {"data": "*"}
    rows: set[tuple[str, str, str]] = set()
    entry_count = 0

    while True:
        response = request_json(endpoint, payload, token)
        entries = response.get("data", [])
        if not isinstance(entries, list):
            raise RuntimeError("Unexpected Oasis response: 'data' is not a list")

        entry_count += len(entries)
        for entry in entries:
            rows.update(extract_pi_rows(entry))

        after = response.get("pagination", {}).get("next_page_after_value")
        if not after:
            break
        payload["pagination"]["page_after_value"] = after

    return sorted(
        rows,
        key=lambda row: tuple(value.casefold() for value in row),
    ), entry_count


def write_csv(rows: list[tuple[str, str, str]], output: Path) -> None:
    """Write the summary rows to a UTF-8 CSV file."""
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(["name", "area", "role"])
        writer.writerows(rows)


LEADERSHIP_ROLES = {"area leader", "deputy area leader", "task leader"}


def area_members(
    rows: list[tuple[str, str, str]],
) -> dict[str, dict[str, bool]]:
    """Group names by area and remember who has a leadership role there."""
    areas: dict[str, dict[str, bool]] = {}
    for name, area, role in rows:
        if not area:
            continue
        members = areas.setdefault(area, {})
        is_leader = role.casefold() in LEADERSHIP_ROLES
        members[name] = members.get(name, False) or is_leader
    return areas


def write_membership_matrix_svg(
    rows: list[tuple[str, str, str]], output: Path
) -> None:
    """Create a readable PI-by-area membership matrix."""
    areas = area_members(rows)
    area_names = sorted(areas)
    people: dict[str, set[str]] = {}
    leader_areas: dict[str, set[str]] = {}
    for name, area, role in rows:
        if not area:
            continue
        people.setdefault(name, set()).add(area)
        if role.casefold() in LEADERSHIP_ROLES:
            leader_areas.setdefault(name, set()).add(area)

    several = sorted(
        (name for name, memberships in people.items() if len(memberships) > 1),
        key=lambda name: (
            -len(people[name]),
            tuple(sorted(people[name])),
            name.casefold(),
        ),
    )
    single = sorted(
        (name for name, memberships in people.items() if len(memberships) == 1),
        key=lambda name: (next(iter(people[name])), name.casefold()),
    )

    width = 1180
    row_height = 27
    top = 155
    group_height = 38
    bottom = 80
    height = top + bottom + len(people) * row_height + 2 * group_height
    name_x = 34
    matrix_x = 620
    column_width = 58
    count_x = matrix_x + len(area_names) * column_width + 45
    svg = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" '
        f'height="{height}" viewBox="0 0 {width} {height}">',
        '<rect width="100%" height="100%" fill="#ffffff"/>',
        '<text x="590" y="42" text-anchor="middle" font-family="Arial, sans-serif" '
        'font-size="28" font-weight="bold">FAIRmat PI Area Membership Matrix</text>',
        '<text x="590" y="72" text-anchor="middle" font-family="Arial, sans-serif" '
        'font-size="15">● member   ◆ Area Leader, Deputy Area Leader, or Task Leader</text>',
        f'<text x="{name_x}" y="125" font-family="Arial, sans-serif" '
        'font-size="15" font-weight="bold">PI</text>',
    ]

    for index, area in enumerate(area_names):
        x = matrix_x + index * column_width
        letter = area.split(" ", 2)[1]
        svg.append(
            f'<text x="{x}" y="125" text-anchor="middle" '
            'font-family="Arial, sans-serif" font-size="17" font-weight="bold">'
            f'<title>{html.escape(area)}</title>{html.escape(letter)}</text>'
        )
    svg.append(
        f'<text x="{count_x}" y="125" text-anchor="middle" '
        'font-family="Arial, sans-serif" font-size="15" font-weight="bold">Areas</text>'
    )

    y = top
    row_number = 0
    for heading, names in (("SEVERAL AREAS", several), ("ONE AREA", single)):
        svg.append(
            f'<rect x="24" y="{y - 22}" width="1132" height="31" fill="#e2e8f0"/>'
        )
        svg.append(
            f'<text x="{name_x}" y="{y}" font-family="Arial, sans-serif" '
            'font-size="15" font-weight="bold" fill="#334155">'
            f'{heading} ({len(names)})</text>'
        )
        y += group_height
        for name in names:
            if row_number % 2:
                svg.append(
                    f'<rect x="24" y="{y - 19}" width="1132" height="{row_height}" '
                    'fill="#f8fafc"/>'
                )
            is_leader = bool(leader_areas.get(name))
            weight = "bold" if is_leader else "normal"
            svg.append(
                f'<text x="{name_x}" y="{y}" font-family="Arial, sans-serif" '
                f'font-size="14" font-weight="{weight}">{html.escape(name)}</text>'
            )
            for index, area in enumerate(area_names):
                x = matrix_x + index * column_width
                if area in people[name]:
                    leader_here = area in leader_areas.get(name, set())
                    mark = "◆" if leader_here else "●"
                    color = "#b45309" if leader_here else "#2563eb"
                    svg.append(
                        f'<text x="{x}" y="{y}" text-anchor="middle" '
                        'font-family="Arial, sans-serif" font-size="17" '
                        f'fill="{color}"><title>{html.escape(name)} — '
                        f'{html.escape(area)}</title>{mark}</text>'
                    )
                else:
                    svg.append(
                        f'<circle cx="{x}" cy="{y - 5}" r="2" fill="#cbd5e1"/>'
                    )
            svg.append(
                f'<text x="{count_x}" y="{y}" text-anchor="middle" '
                'font-family="Arial, sans-serif" font-size="14" font-weight="bold">'
                f'{len(people[name])}</text>'
            )
            y += row_height
            row_number += 1

    svg.append("</svg>")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("\n".join(svg), encoding="utf-8")


def parse_args() -> argparse.Namespace:
    default_output = Path("data") / f"PI_areas_{date.today().isoformat()}.csv"
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api-url", default=os.getenv("NOMAD_API_URL", DEFAULT_API_URL))
    parser.add_argument("--output", "-o", type=Path, default=default_output)
    parser.add_argument(
        "--diagram",
        type=Path,
        help="SVG matrix path; defaults to the CSV name followed by _matrix.svg",
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
        token = args.token
        if not token:
            username = args.username or prompt_username()
            password = os.getenv(args.password_env) or getpass.getpass(
                "Your NOMAD password: "
            )
            token = get_access_token(args.api_url.rstrip("/"), username, password)

        rows, entry_count = query_pi_rows(
            args.api_url.rstrip("/"), token, args.page_size
        )
        write_csv(rows, args.output)
        diagram = args.diagram or args.output.with_name(
            f"{args.output.stem}_matrix.svg"
        )
        write_membership_matrix_svg(rows, diagram)
    except RuntimeError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1

    print(
        f"Found {len(rows)} unique PI area/role assignments in "
        f"{entry_count} matching entries; wrote {args.output} and {diagram}.",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
