#!/usr/bin/env python3

import os
import logging
import logging.handlers
import argparse
import fnmatch
from agithub.GitHub import GitHub
from dotenv import load_dotenv
from pprint import pprint


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


def get_workflow_runs(org_name, repo_name, workflow_id, date_filter):
    # Pagination does not work on this call
    # https://github.com/mozilla/agithub/issues/76

    runs = []
    total_runs_returned = 0
    page_to_get = 1
    more_results = True

    while more_results:
        # repos/{org}}/{repo name}/actions/workflows/{workflow id}/runs
        gh_status, workflow_runs = (
            github_handle.repos[org_name][repo_name]
            .actions.workflows[workflow_id]
            .runs.get(created=date_filter, page=page_to_get)
        )

        runs = runs + workflow_runs["workflow_runs"]

        total_runs = workflow_runs["total_count"]
        runs_returned_in_this_page = len(workflow_runs["workflow_runs"])
        total_runs_returned += runs_returned_in_this_page

        logger.debug(
            "total runs {} Runs this page {} Running count {}".format(
                total_runs, runs_returned_in_this_page, total_runs_returned
            )
        )

        if total_runs_returned < total_runs:
            page_to_get += 1
            logger.debug(
                "We have more runs to get - now getting page {}".format(page_to_get)
            )
        else:
            logger.debug("All runs retrieved")
            more_results = False

    return runs


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
        help="Track stats for all jobs run matching this workflow name pattern (eg. *Deploy*)",
        dest="workflow_pattern",
        required=True,
    )
    parser.add_argument(
        "--date-filter",
        help="Github start/end date filter (eg. 2023-03-01..2023-03-31)",
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

    load_dotenv()

    if "GITHUB_PAT" in os.environ:
        logger.debug("Found GITHUB_PAT in the envrionment")
        github_pat = os.getenv("GITHUB_PAT")
    else:
        logger.error("Missing GITHUB_PAT environment variable - unable to continue")
        exit(1)

    # Initialize connection to Github API
    github_handle = GitHub(token=github_pat, paginate=True)

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
            # Possible states: success, failure, cancelled, skipped, timed_out, action_required, neutral

            deployers = dict()
            workflow_runs = []
            workflow_success_count = 0
            workflow_success_rate = 100
            workflow_success_states = set(
                ["success", "neutral", "cancelled", "skipped", "action_required"]
            )

            workflow_fail_count = 0
            workflow_failure_rate = 0
            workflow_failure_states = set(["failure", "timed_out"])

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
                workflow_runs = get_workflow_runs(
                    args.org_name, repo_name, workflow_id, args.date_filter
                )

                total_workflow_runs = len(workflow_runs)

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

                    for workflow_run in workflow_runs:
                        #logging.debug("NEW WORKFLOW RUN FOUND...")
                        #pprint(workflow_run)
                        workflow_status = workflow_run["conclusion"]
                        job_id = workflow_run["id"]
                        if workflow_run["triggering_actor"]:
                            actor = workflow_run["triggering_actor"]["login"]
                        else:
                            actor = "User is no longer in the org"

                        logging.debug("Workflow run was triggered by {}".format(actor))

                        # Initialize the actors list
                        if actor not in deployers:
                            deployers[actor] = 0

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
                        if workflow_status in workflow_success_states:
                            workflow_success_count += 1
                        elif workflow_status in workflow_failure_states:
                            workflow_fail_count += 1

                        # No matter success or fail, the current actor triggered a deploy
                        deployers[actor] += 1

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

                    # Because we are only counting non-manual runs, we could have 0 actual "runs"
                    # This causes a dividie by zero error
                    if total_workflow_runs == 0:
                        workflow_success_rate = 0
                        workflow_failure_rate = 0
                        workflow_avg_duration = 0
                    else:
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
                        "actors": deployers,
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
                        print("\t\tDeployers:")
                        sorted_deployers = sorted(
                            deployers.items(), key=lambda item: item[1], reverse=True
                        )
                        for deploy_user, deploy_count in sorted_deployers:
                            print("\t\t\t{}:{}".format(deploy_user, deploy_count))

    # now we can process the stats we have gathered and get the overall averages
    workflow_count = 0
    overall_success_sum = 0
    overall_failure_sum = 0
    overall_duration_ms_sum = 0
    overall_run_count = 0
    overall_deployers = dict()

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
            overall_run_count += summary_stats[stat_repo][stat_workflow]["total_runs"]

            # We do not want to include branch deploys in the per-user summary
            if fnmatch.fnmatch(stat_workflow, "Branch*"):
                logging.debug(
                    "Workflow {} is a branch deploy (manual) - skipping deployer stats".format(
                        stat_workflow
                    )
                )
            else:
                for deploy_user, deploy_count in summary_stats[stat_repo][
                    stat_workflow
                ]["actors"].items():
                    if deploy_user in overall_deployers:
                        overall_deployers[deploy_user] += deploy_count
                    else:
                        overall_deployers[deploy_user] = deploy_count

    print("\n")
    print("-------- SUMMARY ---------")
    print(
        "For the period {} with workflows matching {}".format(
            args.date_filter, args.workflow_pattern
        )
    )

    if workflow_count != 0:
        # Finally grab the overall averages
        overall_average_success_rate = format_number(
            overall_success_sum / workflow_count
        )
        overall_average_failure_rate = format_number(
            overall_failure_sum / workflow_count
        )
        overall_average_duration_ms = overall_duration_ms_sum / workflow_count

        print("Total Runs: {}".format(overall_run_count))
        print("Avg Success Rate: {}%".format(overall_average_success_rate))
        print("Avg Failure Rate: {}%".format(overall_average_failure_rate))
        print(
            "Avg Duration:: {:.0f} ms ({})".format(
                overall_average_duration_ms,
                get_mins_secs_str(overall_average_duration_ms),
            )
        )
        print("Non 'Branch Deploy' Deployers:")
        sorted_overall_deployers = sorted(
            overall_deployers.items(), key=lambda item: item[1], reverse=True
        )
        for deploy_user, deploy_count in sorted_overall_deployers:
            print("\t{}:{}".format(deploy_user, deploy_count))
    else:
        print("No workflows found matching the filter and/or date critiera")
