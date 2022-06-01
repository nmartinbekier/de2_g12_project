import json
import os
from typing import Callable, List

from api_wrapper import GithubWrapper, RepoEnumerator
from githubprocessor import GithubProcessor, ProcessingFinishedException
from pulsar_wrapper import PulsarConnection


def run_task(task: Callable[[], bool], run_once: bool):
    ran_once = False

    while task():
        ran_once = True
        if run_once:
            return True

    return ran_once


def run_tasks_until_fail(tasks: List[Callable[[], bool]]):
    for task in tasks:
        if task():
            return


def run_main():
    environment = os.environ

    pulsar_host = environment.get('pulsar_host')
    debug = environment.get('debug', 'false').lower() == 'true'

    pulsar = PulsarConnection(
        ip_address=pulsar_host
    )

    processor = GithubProcessor(
        pulsar=pulsar,
        verbose=debug
    )

    # Prioritize tasks as (from most prioritized to least):
    # 1. Try to analyze if a repo has ci or not
    # 2. Analyze if a repo has tests or not
    # 3. Find commit count for repos
    # 4. Find repos

    tasks = [
        processor.analyze_repo_ci,
        processor.analyze_repo_tests,
        processor.analyze_repo_commits,
        processor.read_repos,
        processor.process_results
    ]

    try:
        while True:
            # run_once = False
            # for task in tasks:
            #     # If the task produces a result, the preceding task
            #     # has data to process, and therefore,
            #     run_task(task, run_once)
            #     run_once = True

            # Iterate over all tasks in the specified order
            run_tasks_until_fail(tasks)
            # for task in tasks:
            #     if task():
            #         # If task completes successfully, break and restart iterating through tasks
            #         # so that the most prioritized tasks are done as long as they complete successfully,
            #         # and when not successful,
            #         break
    except ProcessingFinishedException:
        print("Results were produced. Processing has finished. Exiting.")


if __name__ == "__main__":
    run_main()
