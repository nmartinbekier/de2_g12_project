import random
import uuid
from typing import List, Dict

import requests


def find_property(tree: Dict, path: List[str]):
    result = tree
    for way in path:
        if result is None:
            return None

        result = result[way]

    return result


class RepoName:
    def __init__(self, owner: str, name: str, repo_id: int = -1):
        self.owner = owner
        self.name = name
        self.id = repo_id
        self.uuid = uuid.uuid4()

    def __str__(self):
        return f"{self.owner}/{self.name}"

    def __repr__(self):
        return f"{self.owner}/{self.name}"


class RepoStats:
    def __init__(self, name: RepoName, commits: int, primary_language: str, primary_language_id: str):
        self.name = name
        self.commits = commits
        self.primary_language = primary_language
        self.primary_language_id = primary_language_id

    def __str__(self):
        return f"{self.name}: ( commits: {self.commits}, lang: {self.primary_language}, lang_id: {self.primary_language_id} )"

    def __repr__(self):
        return f"{self.name}: ( commits: {self.commits}, lang: {self.primary_language}, lang_id: {self.primary_language_id} )"

    def to_dict(self):
        return {
            "owner": self.name.owner,
            "name": self.name.name,
            "id": self.name.id,
            "commits": self.commits,
            "primary_language": self.primary_language,
            "primary_language_id": self.primary_language_id
        }


class Github:
    def __init__(self,
                 auth_tokens: List[str],
                 graphql_url: str = 'https://graphql.github.com',
                 repositories_url: str = 'https://api.github.com/repositories'):
        self.tokens = auth_tokens
        self.query_template = open("repo_query.graphql", "r").read()
        self.graphql_url = graphql_url
        self.repositories_url = repositories_url

    @staticmethod
    def read_tokens_from_file(file_path: str):
        return [token.split("#")[0].strip() for token in open("tokens.txt", "r").readlines()]

    def get_token(self):
        return random.choice(self.tokens)

    def get_repos_with_stats(self, start_index: int = 0):
        repos = self.get_repos(start_index)
        return self.get_stats(repos)

    def get_repos(self, start_index: int = 0):
        headers = {
            'Accept': 'application/vnd.github.v3+json'
        }

        params = {
            'since': start_index
        }

        response = requests.get(
            self.repositories_url,
            headers=headers,
            params=params)

        repo_list = response.json()
        results = []

        for repo in repo_list:
            results.append(RepoName(
                name=repo["name"],
                owner=repo["owner"]["login"],
                repo_id=int(repo["id"])
            ))

        return results

    def get_stats(self, repos: List[RepoName]):
        # GraphQL used for this is from the following stackoverflow thread:
        # https://stackoverflow.com/questions/27931139/how-to-use-github-v3-api-to-get-commit-count-for-a-repo
        headers = {
            'User-Agent': 'DE2 github project bot',
            'Accept': '*/*',
            'Accept-Language': 'en-US,en;q=0.5',
            'Authorization': 'bearer ' + self.get_token(),
            'Origin': self.graphql_url,
            'DNT': '1',
            'Connection': 'keep-alive',
            'Sec-Fetch-Dest': 'empty',
            'Sec-Fetch-Mode': 'cors',
            'Sec-Fetch-Site': 'same-origin',
            'Sec-GPC': '1',
        }

        repo_template = '  repo_$INDEX: repository(owner: "$OWNER", name: "$REPO") {\n    ...RepoFragment\n  }\n'

        repo_templates = '\n'.join([
            repo_template
                .replace("$INDEX", repo_name.uuid.hex) \
                .replace("$OWNER", repo_name.owner) \
                .replace("$REPO", repo_name.name)
            for repo_name in repos
        ])

        query = self.query_template.replace("$REPOS", repo_templates)

        json_data = {
            'query': query,
            'variables': {},
        }

        response = requests.post('https://api.github.com/graphql', headers=headers,
                                 json=json_data)

        response_dict = response.json()
        result_dict = response_dict["data"]
        results = {}

        paths = {
            'owner': ['owner', 'login'],
            'lang_id': ['primaryLanguage', 'id'],
            'lang_name': ['primaryLanguage', 'name'],
            'commits': ['defaultBranchRef', 'target', 'history', 'totalCount']
        }

        for repo_name in repos:
            repo_results = result_dict[f"repo_{repo_name.uuid.hex}"]
            name = repo_results["name"]
            owner = find_property(repo_results, paths['owner'])

            assert repo_name.name == name
            assert repo_name.owner == owner

            lang_id = find_property(repo_results, paths['lang_id'])
            lang_name = find_property(repo_results, paths['lang_name'])
            commits = find_property(repo_results, paths['commits'])

            results[str(repo_name)] = RepoStats(
                name=repo_name,
                commits=commits,
                primary_language=lang_name,
                primary_language_id=lang_id
            )

        return results


class RepoEnumerator:
    def __init__(self,
                 api: Github,
                 start_index: int,
                 end_index: int,
                 step_size: int):
        self.api = api
        self.index = start_index
        self.end_index = end_index
        self.step_size = step_size

    def _change_index(self):
        self.index = self._get_next_index()

    def _get_next_index(self):
        return self.index + self.step_size

    def is_done(self):
        return self.index >= self.end_index if self.step_size > 0 else self.index <= self.end_index

    def get(self):
        current_index = self.index
        self._change_index()

        return self.api.get_repos_with_stats(
            start_index=current_index
        )
