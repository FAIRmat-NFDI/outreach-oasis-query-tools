# FAIRmat Outreach Oasis People Exporter

A small command-line tool for exporting names and email addresses from the
[FAIRmat Outreach NOMAD Oasis](https://fairmat-oasis.physik.hu-berlin.de).

The tool presents an interactive Area and task menu, queries the matching
Person entries, removes duplicates, and saves the result as a CSV file.

## Features

- Interactive selection of FAIRmat Areas A–H
- Task choices limited to the selected Area
- **All areas** and **All tasks** options
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

## Testing

Run the automated tests from the repository directory:

```powershell
python -m unittest -v
```

The tests do not contact the live Oasis or require login credentials.

## Project structure

```text
.
|-- query_PIs_emails.py   Interactive query and CSV export tool
|-- query.json            Example saved Oasis query
|-- test_query_PIs_emails.py  Automated tests
|-- data/                 Local generated CSV output (`.gitkeep` preserves the folder)
|-- .gitignore            Excludes CSV files, credentials, and Python cache
`-- README.md
```

## Security and data handling

- Usernames and passwords are not saved by the script.
- Passwords should not be placed directly in commands because shell history may
  retain them.
- `.env` files and all generated CSV files are excluded from Git by default.
- `data/.gitkeep` keeps the output directory in the repository without committing
  its generated CSV files.
- Exported names and email addresses may be personal data. Share and retain the
  CSV files only as permitted by your organization and applicable data-protection
  requirements.

For unattended use, credentials can be supplied through `NOMAD_USERNAME` and
`NOMAD_PASSWORD` environment variables. Avoid storing these variables in files
committed to the repository.
