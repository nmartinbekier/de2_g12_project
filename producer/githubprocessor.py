import time
from typing import Callable, Optional, List, Tuple

from more_itertools import take

from api_wrapper import GithubWrapper, RepoName, RateLimitException
from pulsar_wrapper import PulsarConnection
from github import Github, RateLimitExceededException


class ProcessingFinishedException(Exception):
    pass


class GithubProcessor:
    def __init__(self,
                 pulsar: PulsarConnection,
                 no_token_sleep: int = 10,
                 verbose: bool = False):
        self.pulsar = pulsar
        self.no_token_sleep = no_token_sleep
        self.verbose = verbose

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

    def _log(self, message):
        if not self.verbose:
            return

        print(message)

    def _get_token(self):
        while True:
            # Attempt to get a
            token = self.pulsar.get_free_token()

            if token is not None:
                return token

            # Check all standby tokens to see if they have
            # still exceeded the rate limit
            self._log("Checking tokens")
            if not self._check_tokens():
                # All seen standby tokens still exceed rate limit,
                # Sleep and retry again later
                if self.no_token_sleep > 0:
                    self._log("Sleeping until next token check")
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
        self._log(f"{__name__}: attempting to check tokens")
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
        return Github(token, per_page=100)

    def _create_wrapped_api(self, token):
        return GithubWrapper([token])

    def process_results(self):
        self.pulsar.process_results()
        raise ProcessingFinishedException

    def read_repos(self):
        return self.run_with_token(self._read_repos)

    def _read_repos(self, token: str, count: int = 100) -> bool:
        self._log(f"{__name__}: attempting to read repos")
        day = self.pulsar.get_day_to_process()

        if day is None:
            self._log(f"{__name__}: received no day to read repos from.")
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

        self._log(f"{__name__}: read {len(basic_repo_info)} repos")
        self.pulsar.put_basic_repo_info(basic_repo_info)
        return True

    def analyze_repo_commits(self):
        return self.run_with_token(self._analyze_repo_commits)

    def _analyze_repo_commits(self, token: str) -> bool:
        self._log(f"{__name__}: attempting to analyze repo commits")
        repos = self.pulsar.get_repos_for_commit_count(num_repos=100)

        if repos is None or len(repos) < 1:
            self._log(f"{__name__}: no repos to analyze commits for")
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

        self._log(f"{__name__}: read commits for {len(repos_with_commits)} repos")
        self.pulsar.put_commit_repo_info(repos_with_commits)
        return True

    def analyze_repo_ci(self) -> bool:
        return self.run_with_token(self._analyze_repo_ci)

    def _analyze_repo_ci(self, token: str) -> bool:
        self._log(f"{__name__}: attempting to analyze repo ci")
        status = self._get_and_query_repo(
            token=token,
            retriever=self.pulsar.get_repo_with_tests,
            query_files=self.ci_files,
            output=self.pulsar.put_repo_with_ci
        )

        if status:
            self._log(f"{__name__}: analyzed ci for at least one repo")
        else:
            self._log(f"{__name__}: no repos to analyze ci for")

        return status

    def analyze_repo_tests(self) -> bool:
        return self.run_with_token(self._analyze_repo_tests)

    def _analyze_repo_tests(self, token: str) -> bool:
        self._log(f"{__name__}: attempting to analyze repo tests")
        status = self._get_and_query_repo(
            token=token,
            retriever=self.pulsar.get_repos_for_test_check,
            query_files=self.test_files,
            output=self.pulsar.put_repo_with_tests
        )

        if status:
            self._log(f"{__name__}: analyzed tests for at least one repo")
        else:
            self._log(f"{__name__}: no repos to analyze tests for")

        return status

    def _get_and_query_repo(self,
                            token: str,
                            retriever: Callable[[int], List],
                            query_files: List[str],
                            output: Callable[[List], None],
                            batch_size: int = 1) -> bool:
        repos = retriever(batch_size)

        if repos is None or len(repos) < 1:
            return False

        for repo in repos:
            self._query_repo(
                token=token,
                repo=repo,
                search_files=query_files,
                consumer=output
            )

        return True

    def _query_repo(self,
                    token: str,
                    repo: (str, str, str, str),
                    search_files: List[str],
                    consumer: Callable[[List], None]) -> None:
        wrapper = self._create_wrapped_api(token)

        repo_id, owner, name, language = repo
        repo_name = RepoName(
            owner=owner,
            name=name,
            repo_id=repo_id)

        files = wrapper.get_files(
            repo_name=repo_name,
            file_names=search_files
        )

        if files is not None and len(files) > 0:
            consumer([repo_id, language])

    def run_with_token(self, function: Callable[[str], bool]) -> bool:
        token = self._get_token()
        result = False

        try:
            result = function(token)
            self.pulsar.put_free_token(token)
        except (RateLimitExceededException, RateLimitException):
            self.pulsar.put_standby_token(token)
            return self.run_with_token(function)

        return result
