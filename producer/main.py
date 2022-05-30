import json
import os
from typing import Callable

from api_wrapper import GithubWrapper, RepoEnumerator
from githubprocessor import GithubProcessor
from pulsar_wrapper import PulsarConnection


def run_task(task: Callable[[], bool], run_once: bool):
    ran_once = False

    while task():
        ran_once = True
        if run_once:
            return True

    return ran_once


def run_main():
    environment = os.environ

    pulsar_host = environment.get("pulsar_host")
    debug = environment.get("debug")

    pulsar = PulsarConnection(ip_address=pulsar_host)
    processor = GithubProcessor(pulsar=pulsar)

    tasks = [
        processor.analyze_repos,
        processor.read_repos
    ]

    while True:
        run_once = False
        for task in tasks:
            # If the task produces a result, the preceding task
            # has data to process, and therefore,
            run_task(task, run_once)
            run_once = True

        # Iterate over all tasks in the specified order
        for task in tasks:
            if task():
                # If task completes successfully, break and restart iterating through tasks
                # so that the most prioritized tasks are done as long as they complete successfully,
                # and when not successful,
                break


if __name__ == "__main__":
    run_main()
