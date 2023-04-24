#!/usr/bin/env python3

import logging
import logging.handlers
import argparse
from agithub.GitHub import GitHub
import fnmatch
from pprint import pformat, pprint


def get_mins_secs_str(duration_in_ms):
    duration_secs, duration_in_ms = divmod(duration_in_ms, 1000)
    duration_mins, duration_secs = divmod(duration_secs, 60)

    return str(round(duration_mins)) + "m " + str(round(duration_secs)) + "s"


def format_number(float_val):
    if float_val.is_integer():
        return_val = int(float_val)
    else:
        return_val = "{0:.2f}".format(float_val)

    return str(return_val)


if __name__ == "__main__":
    summary_stats = dict()

    description = "Gather deployment metrics from Github actions\n"

    parser = argparse.ArgumentParser(
        description=description, formatter_class=argparse.RawTextHelpFormatter
    )

    parser.add_argument(
        "--org-name", help="Github organization name", dest="org_name", required=True
    )
    parser.add_argument(
        "--deploy-workflow-pattern",
        help="Github actions deploy workflows",
        dest="workflow_pattern",
        required=True,
    )
    parser.add_argument(
        "--github-pat", help="Github access token", dest="github_pat", required=True
    )
    parser.add_argument(
        "--date-filter",
        help="Github start/end date filter",
        dest="date_filter",
        required=True,
    )
    parser.add_argument(
        "--detailed", help="Show detailed output for each repo", action="store_true"
    )
    parser.add_argument(
        "--include-manual-runs",
        help="Include manual workflow runs in stats computations",
        dest="include_manual_runs",
        action="store_true",
    )
    parser.add_argument(
        "--verbose", help="Turn on DEBUG logging", action="store_true", required=False
    )

    args = parser.parse_args()

    log_level = logging.INFO

    if args.verbose:
        print("Verbose logging selected")
        log_level = logging.DEBUG

    # Setup some logging
    logger = logging.getLogger()
    logger.setLevel(log_level)
    ch = logging.StreamHandler()
    ch.setLevel(log_level)
    console_formatter = logging.Formatter("%(levelname)8s: %(message)s")
    ch.setFormatter(console_formatter)
    logger.addHandler(ch)

    # Initialize connection to Github API
    github_handle = GitHub(token=args.github_pat, paginate=True)
    # github_handle = GitHub(token=args.github_pat)

    # Get all the repos in the org
    # /orgs/{org}/repos
    gh_status, repo_data = github_handle.orgs[args.org_name].repos.get()

    for repo in repo_data:
        repo_name = repo["name"]
        repo_printed = False

        logger.debug("Processing repo {}".format(repo_name))

        if repo["archived"]:
            logger.debug("repo {} is archived - skipping".format(repo_name))
            continue

        # Now for each repo, see if we have a deployment workflow matching the pattern
        # /repos/{org}/{repo name}/actions/workflows
        gh_status, workflow_data = github_handle.repos[args.org_name][
            repo_name
        ].actions.workflows.get()

        for workflow in workflow_data["workflows"]:
            workflow_success_count = 0
            workflow_success_rate = 100

            workflow_fail_count = 0
            workflow_failure_rate = 0

            workflow_avg_duration = 0
            workflow_total_duration = 0

            workflow_id = workflow["id"]
            workflow_name = workflow["name"]
            workflow_summary_name = workflow_name.replace(
                " ", ""
            )  # Dicts cannot have spaces in keys

            logging.debug("Found workflow {}".format(workflow_name))

            if fnmatch.fnmatch(workflow_name, args.workflow_pattern):
                logging.debug(
                    "workflow {} matches {}".format(
                        workflow_name, args.workflow_pattern
                    )
                )

                # We have a matching workflow - get the runs for it in our timeframe
                # repos/{org}}/{repo name}/actions/workflows/{workflow id}/runs
                gh_status, workflow_runs = (
                    github_handle.repos[args.org_name][repo_name]
                    .actions.workflows[workflow_id]
                    .runs.get(created=args.date_filter)
                )

                total_workflow_runs = len(workflow_runs["workflow_runs"])

                logging.debug(
                    "Found {} workflow runs for {}".format(
                        total_workflow_runs, workflow_name
                    )
                )

                # Were there any runs for this workflow in this time period?
                if total_workflow_runs > 0:
                    if args.detailed and not repo_printed:
                        print("{}".format(repo_name))
                        repo_printed = True

                    # Initialize our summary stats dict
                    if repo_name not in summary_stats:
                        summary_stats[repo_name] = dict()

                    for workflow_run in workflow_runs["workflow_runs"]:
                        workflow_status = workflow_run["conclusion"]
                        job_id = workflow_run["id"]

                        # Manual runs are generally used for testing so exclude them by default
                        if workflow_run["event"] == "workflow_dispatch":
                            if args.include_manual_runs:
                                logging.debug(
                                    "Workflow run {} was manually invoked and include-manual-runs is set - including in stats".format(
                                        job_id
                                    )
                                )
                            else:
                                logging.debug(
                                    "Workflow run {} was manually invoked - excluding from stats".format(
                                        job_id
                                    )
                                )
                                total_workflow_runs -= 1
                                continue

                        logging.debug(
                            "Workflow status for {} is {}".format(
                                workflow_name, workflow_status
                            )
                        )

                        # Get the success/fail status of these runs
                        if workflow_status == "success":
                            workflow_success_count += 1
                        else:
                            # there are multiple failure status values. Assume non-success == failure
                            workflow_fail_count += 1

                        # How long did this run run for
                        # repos/{org}/{repo}/actions/runs/{run id}/timing
                        gh_status, workflow_durations = (
                            github_handle.repos[args.org_name][repo_name]
                            .actions.runs[job_id]
                            .timing.get()
                        )

                        # Some jobs may not have run at all
                        if "run_duration_ms" in workflow_durations:
                            job_duration = workflow_durations["run_duration_ms"]
                        else:
                            job_duration = 0

                        workflow_total_duration += job_duration

                        logging.debug(
                            "Job {} ran for {} ms and ended with status {}".format(
                                job_id, job_duration, workflow_status
                            )
                        )

                    # Assemble our stats record for this workflow in this repo
                    workflow_success_rate = format_number(
                        100.0 * workflow_success_count / total_workflow_runs
                    )
                    workflow_failure_rate = format_number(
                        100.0 * workflow_fail_count / total_workflow_runs
                    )
                    workflow_avg_duration = float(workflow_total_duration) / float(
                        total_workflow_runs
                    )

                    stat = {
                        "total_runs": total_workflow_runs,
                        "success_count": workflow_success_count,
                        "fail_count": workflow_fail_count,
                        "success_rate": workflow_success_rate,
                        "fail_rate": workflow_failure_rate,
                        "avg_duration_ms": workflow_avg_duration,
                    }
                    summary_stats[repo_name][workflow_summary_name] = stat

                    if args.detailed:
                        print("\t{}:".format(workflow_name))
                        print("\t\tRuns: {}".format(total_workflow_runs))
                        print("\t\tSuccessful: {}".format(workflow_success_count))
                        print("\t\tFailed: {}".format(workflow_fail_count))
                        print("\t\tSuccess Rate: {}%".format(workflow_success_rate))
                        print(
                            "\t\tAvg Duration:: {:.0f} ms ({})".format(
                                workflow_avg_duration,
                                get_mins_secs_str(workflow_avg_duration),
                            )
                        )

    # now we can process the stats we have gathered and get the overall averages
    workflow_count = 0
    overall_success_sum = 0
    overall_failure_sum = 0
    overall_duration_ms_sum = 0

    for stat_repo in summary_stats:
        for stat_workflow in summary_stats[stat_repo]:
            workflow_count += 1
            overall_success_sum += float(
                summary_stats[stat_repo][stat_workflow]["success_rate"]
            )
            overall_failure_sum += float(
                summary_stats[stat_repo][stat_workflow]["fail_rate"]
            )
            overall_duration_ms_sum += summary_stats[stat_repo][stat_workflow][
                "avg_duration_ms"
            ]

    # Finally grab the overall averages
    overall_average_success_rate = format_number(overall_success_sum / workflow_count)
    overall_average_failure_rate = format_number(overall_failure_sum / workflow_count)
    overall_average_duration_ms = overall_duration_ms_sum / workflow_count

    print("\n")
    print("-------- SUMMARY ---------")
    print(
        "For the period {} with workflows matching {}".format(
            args.date_filter, args.workflow_pattern
        )
    )
    print("Avg Success Rate: {}%".format(overall_average_success_rate))
    print("Avg Failure Rate: {}%".format(overall_average_failure_rate))
    print(
        "Avg Duration:: {:.0f} ms ({})".format(
            overall_average_duration_ms, get_mins_secs_str(overall_average_duration_ms)
        )
    )
