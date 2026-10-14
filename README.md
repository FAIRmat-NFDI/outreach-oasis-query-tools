# FAIRmat Outreach Oasis People Exporter

A small command-line tool for exporting names and email addresses from the
[FAIRmat Outreach NOMAD Oasis](https://fairmat-oasis.physik.hu-berlin.de).

The tool presents an interactive Area and task menu, queries matching Principal
Investigator (PI) entries, removes duplicates, and saves the result as a CSV
file.

## Features

- Interactive selection of FAIRmat Areas A–H
- Task choices limited to the selected Area
- **All areas** and **All tasks** options
- PI-only results for every selection, including **All areas**, **All tasks**,
  and saved queries
- Excludes the legacy **FAIRmat1 Area E – Use Cases** category
- Automatic pagination through all matching Oasis entries
- Deduplicated `name,email` output
- Automatically dated filenames in the `data` directory
- No third-party Python packages required

## Requirements

- Python 3.9 or newer
- A FAIRmat Outreach Oasis account with access to the requested entries

Check your Python installation with:

```powershell
python --version
```

## Installation

Clone or download this repository, then open a terminal in its directory:

```powershell
git clone https://github.com/FAIRmat-NFDI/outreach-oasis-query-tools.git
cd outreach-oasis-query-tools
```

No package installation is necessary because the script uses only Python's
standard library.

## Usage

Start the interactive exporter:

```powershell
python .\query_PIs_emails.py
```

The script will ask you to:

1. Select an Area, or select **All areas**.
2. Select a task belonging to that Area, or select **All tasks**.
3. At `Your NOMAD username:`, enter your NOMAD username.
4. At `Your NOMAD password:`, enter your NOMAD password.

Password input is hidden while typing. A successful query creates a file such
as:

```text
data\Area_B_TaskB1-Hyperspectral_Imaging_2026-09-21.csv
```

The CSV has the following structure:

```csv
name,email
Example Person,person@example.org
```

### Access-token authentication

An existing access token can be used instead of entering a username and
password:

```powershell
$env:NOMAD_TOKEN = "your-access-token"
python .\query_PIs_emails.py
```

### Command-line options

Pass a username on the command line while keeping the password prompt:

```powershell
python .\query_PIs_emails.py --username "your-username"
```

Choose a custom output path:

```powershell
python .\query_PIs_emails.py --output .\data\my_export.csv
```

Run a saved API query instead of using the Area and task menus:

```powershell
python .\query_PIs_emails.py --query .\query.json
```

View every available option:

```powershell
python .\query_PIs_emails.py --help
```

### Generate all proposal-verified Apple Mail lists

`generate_all_email_lists.py` retrieves all PI Person records in one paginated
Oasis query, derives every Area A-H and task A1-G3 membership locally, then
cross-checks the names against a local `proposal_rosters.json`. It writes 31
plain-text recipient lists in Apple Mail's `Name <email>, Name <email>` format,
supporting CSV files, and an audit of missing or excluded names.

The real proposal roster contains personal data and is intentionally excluded
from this public repository. `proposal_rosters.example.json` documents the
required structure using synthetic names. Authorized FAIRmat collaborators can
request the current roster from [Joseph F. Rudzinski](mailto:joseph.rudzinski@physik.hu-berlin.de)
([@JFRudzinski](https://github.com/JFRudzinski)). Please do not post roster or
recipient data in a public GitHub issue. Save the supplied file as
`proposal_rosters.json` beside the scripts, or keep it elsewhere and pass its
location with `--rosters /secure/path/proposal_rosters.json`.

Set an access token without saving it in this repository, then run:

```powershell
$env:NOMAD_TOKEN = "your-access-token"
python .\generate_all_email_lists.py
```

On macOS/Linux, if credentials are stored in the git-ignored `.env` file, load
them into the environment before running:

```bash
set -a
source .env
set +a
python3 generate_all_email_lists.py
```

By default, results are written to a dated directory under `data`. Only names
verified against the proposal roster or as confirmed PI deputies are included
in the paste-ready lists; discrepancies remain visible in `AUDIT.md` for review.
Oasis-only people absent from the proposal are also written to the paste-ready
`oasis_only_recipients.txt` file and to `oasis_only_people.csv`, which records
their Oasis area/task assignments.
PI deputies are discovered automatically from `Deputy for ...` text in the
Oasis Person `notes` field. After validating the represented PI against the
proposal, their `fairmat_roles` assignments place them in the corresponding
area/task lists. Confirmed deputies are documented in `pi_deputies.csv` and
`pi_deputies_recipients.txt`. Unresolved deputy notes or malformed assignments
are excluded and reported in `AUDIT.md` instead of being guessed.

## Testing

Run the automated tests from the repository directory:

```powershell
python -m unittest -v
```

The tests do not contact the live Oasis or require login credentials.

## Project structure

```text
.
|-- query_PIs_emails.py              Interactive query and CSV export tool
|-- generate_all_email_lists.py      Proposal/deputy-verified batch exporter
|-- proposal_rosters.example.json    Synthetic example of the local roster schema
|-- query.json                       Example saved Oasis query
|-- test_query_PIs_emails.py         Interactive-exporter tests
|-- test_generate_all_email_lists.py Batch-exporter and deputy-discovery tests
|-- data/                            Local generated output (`.gitkeep` preserves it)
|-- .gitignore                       Excludes generated lists, credentials, and caches
`-- README.md
```

## Security and data handling

- Usernames and passwords are not saved by the script.
- Passwords should not be placed directly in commands because shell history may
  retain them.
- `.env` files and dated generated-list directories are excluded from Git by
  default.
- The real `proposal_rosters.json` is excluded from Git; only the synthetic
  example is public.
- `data/.gitkeep` keeps the output directory in the repository without committing
  its generated CSV files.
- Exported names and email addresses may be personal data. Share and retain the
  CSV files only as permitted by your organization and applicable data-protection
  requirements.

For unattended use, credentials can be supplied through `NOMAD_USERNAME` and
`NOMAD_PASSWORD` environment variables. Avoid storing these variables in files
committed to the repository.
