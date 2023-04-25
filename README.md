# github-deployment-metrics
Pulls metrics from github actions around deployments

## Installation

```bash
git clone rewindio/github-deployment-metrics
pip3 install -r requirements.txt
```

## Prerequistes

- A Github Personal Access Token (PAT) that has repo and admin:org scopes
- The Github PAT set in an environment variable named `GITHUB_PAT` OR contained in a `.env` file

## Usage

```bash
usage: get-deployment-metrics.py [-h] --org-name ORG_NAME --deploy-workflow-pattern WORKFLOW_PATTERN --date-filter DATE_FILTER [--detailed] [--include-manual-runs] [--verbose]

Gather deployment metrics from Github actions

options:
  -h, --help            show this help message and exit
  --org-name ORG_NAME   Github organization name
  --deploy-workflow-pattern WORKFLOW_PATTERN
                        Track stats for all jobs run matching this workflow name pattern (eg. *Deploy*)
  --date-filter DATE_FILTER
                        Github start/end date filter (eg. 2023-03-01..2023-03-31)
  --detailed            Show detailed output for each repo
  --include-manual-runs
                        Include manual workflow runs in stats computations
  --verbose             Turn on DEBUG logging
```

### Example Execution

```bash
./get-deployment-metrics.py --org-name acme --deploy-workflow-pattern '*Deploy*' --date-filter '2023-03-01..2023-03-31' --detailed
```

### Notes

* By default, manually invoked workflows are skipped and not included in the metrics. You can override this with the `--include_manual_runs` flag
* Archived repos are ignored
* The date-filter option uses the [Github date filtering](https://docs.github.com/en/search-github/getting-started-with-searching-on-github/understanding-the-search-syntax#query-for-dates) syntax
* The `deploy-workflow-pattern` must be a valid pattern as supported by the [python fnmatch](https://docs.python.org/3/library/fnmatch.html) module
