import json
import os
import pulsar
from api_wrapper import Github, RepoEnumerator

if __name__ == '__main__':
    environment = os.environ

    worker_count = int(environment["worker_count"])
    worker_index = int(environment["worker_index"])
    start = int(environment["start_index"])
    end = int(environment["end_index"])
    tokens = environment.get("tokens")
    order = environment.get("order")

    pulsar_host = environment.get("pulsar_host")
    pulsar_topic = environment.get("pulsar_topic")
    pulsar_partition = environment.get("pulsar_partition")
    debug = environment.get("debug")

    if debug is not None and debug != "1":
        debug = None

    if order is not None:
        order = order.lower().strip()
        if order == "ascending":
            order = 1
        elif order == "descending":
            order = -1
        else:
            raise Exception("Invalid order value specified. Specify ascending or descending.")
    else:
        order = 1

    if tokens is not None:
        tokens = [token for token in tokens.split(',')]
    else:
        tokens = Github.read_tokens_from_file("tokens.txt")

    # Create a pulsar client by supplying ip address and port
    client = pulsar.Client(pulsar_host)

    producer = client.create_producer(pulsar_topic)

    api = Github(
        auth_tokens=tokens
    )

    chunk_size = worker_count * 100
    my_start = start - worker_index * 100

    enumerator = RepoEnumerator(
        api,
        start_index=my_start,
        end_index=end,
        step_size=order * chunk_size * worker_count,
    )

    while not enumerator.is_done():
        repos = api.get_repos_with_stats(0)

        for repo_stats in repos.values():
            repo_dict = repo_stats.to_dict()
            json_str = json.dumps(repo_dict, indent=None)
            producer.send(json_str.encode('utf-8'), partition_key=pulsar_partition)

            if debug is not None:
                print(json_str)

    client.close()
