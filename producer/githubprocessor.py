import time
from typing import Callable, Optional

from more_itertools import take

from api_wrapper import GithubWrapper, RepoName, RateLimitException
from pulsar_wrapper import PulsarConnection
from github import Github, RateLimitExceededException


class GithubProcessor:
    def __init__(self, pulsar: PulsarConnection, no_token_sleep: int = 10):
        self.pulsar = pulsar
        self.no_token_sleep = no_token_sleep

        self.ci_files = [
            '.travis.yml',
            '.gitlab-ci.yml',
            '.drone.yml',
            '.circleci',
            '.github/workflows'
        ]

        self.test_files = [
            'test*'
        ]

    def _get_token(self):
        while True:
            # Attempt to get a
            token = self.pulsar.get_free_token()

            if token is not None:
                return token

            # Check all standby tokens to see if they have
            # still exceeded the rate limit
            if not self._check_tokens():
                # All seen standby tokens still exceed rate limit,
                # Sleep and retry again later
                if self.no_token_sleep > 0:
                    time.sleep(self.no_token_sleep)

    @staticmethod
    def _get_all_tokens(retriever):
        tokens = []

        while True:
            token = retriever()

            if token is None:
                return tokens

            tokens.append(token)

    def _check_tokens(self):
        # Keep track of removed tokens in case of exception
        # in order to be able to re-add them as standby
        tokens = GithubProcessor._get_all_tokens(self.pulsar.get_standby_token)
        result = False

        try:
            # Duplicate list to allow for removing elements
            # while iterating properly
            for token in list(tokens):
                limit = GithubWrapper.get_rate_limit(token)

                if limit.is_exceeded():
                    # Rate limit is exceeded, put it back in standby
                    self.pulsar.put_standby_token(token)
                else:
                    # No rate limit is exceeded, put token in free
                    self.pulsar.put_free_token(token)
                    tokens.remove(token)
                    result = True

            return result
        except:
            # Re-add tokens still in list in case of exception
            for token in tokens:
                self.pulsar.put_standby_token(token)
            raise

    def _create_pyapi(self, token):
        return Github(token)

    def _create_wrapped_api(self, token):
        return GithubWrapper([token])

    def read_repos(self):
        return self.run_with_token(self._read_repos)

    def _read_repos(self, token: str, count: int = 100) -> bool:
        day = self.pulsar.get_day_to_process()

        if day is None:
            return False

        repos = list(take(count, self \
            ._create_pyapi(token) \
            .search_repositories(query=f'created:{day}')))

        basic_repo_info = list(map(
            lambda repo: (
                repo.id,
                repo.owner.login,
                repo.name,
                repo.language
            ),
            repos
        ))

        self.pulsar.put_basic_repo_info(basic_repo_info)
        return True

    def analyze_repos(self):
        return self.run_with_token(self._analyze_repos)

    def _analyze_repos(self, token: str) -> bool:
        repos = self.pulsar.get_basic_repo_info(num_repos=100)

        if repos is None or len(repos) < 1:
            return False

        repo_names = list(map(
            lambda repo_tuple: RepoName(
                name=repo_tuple[2],
                owner=repo_tuple[1],
                repo_id=repo_tuple[0]
            ),
            repos
        ))

        wrapped_api = self._create_wrapped_api(token=token)
        repos_with_stats = wrapped_api.get_stats(repo_names)

        repos_with_commits = list(map(
            lambda repo_with_stats: (
                repo_with_stats.name.id,
                repo_with_stats.commits,
                repo_with_stats.name.owner,
                repo_with_stats.name.name
            ),
            repos_with_stats.values()
        ))

        self.pulsar.put_commit_repo_info(repos_with_commits)

        for repo in repos:
            self._query_repo(token, repo)

        return True

    def _query_repo(self, token: str, repo: (str, str, str, str)) -> None:
        wrapper = self._create_wrapped_api(token)

        repo_id, owner, name, language = repo
        repo_name = RepoName(
            owner=owner,
            name=name,
            repo_id=repo_id)

        query_areas = [
            (self.ci_files, self.pulsar.put_repo_with_ci),
            (self.test_files, self.pulsar.put_repo_with_tests)
        ]

        for (search_files, consumer) in query_areas:
            files = wrapper.get_files(
                repo_name=repo_name,
                file_names=search_files
            )

            if files is not None and len(files) > 0:
                consumer([repo_id, language])

    def run_with_token(self, function: Callable[[str], bool]):
        token = self._get_token()

        try:
            result = function(token)
            self.pulsar.put_free_token(token)
            return result
        except (RateLimitExceededException, RateLimitException):
            self.pulsar.put_standby_token(token)
            return False
