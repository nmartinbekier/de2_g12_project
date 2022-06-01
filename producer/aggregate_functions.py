"""
To enable this, it has to be called by pulsar admin. Adjust depending on 'aggregate_functions.py' path
$ bin/pulsar-admin functions create \
  --py ~/de2_g12_project/producer/aggregate_functions.py \
  --classname aggregate_functions.AggregateFunction \
  --tenant public \
  --namespace static \
  --name aggregate_functions \
  --inputs persistent://public/default/basic_repo_info,persistent://public/default/repo_with_tests,persistent://public/static/repo_with_ci,persistent://public/static/aggregate_languages_info 

Some counters and topics we're using:
Global counters:
- *repo_id* : a 1 indicates that the repository has already been reviewed
- *repo_id*-tests : a 1 indicates that the repository has been reviewed for tests
- *language*-repos: counts number of repositories in *language*
- *language*-tests: counts number of repositories of *language* that use tests
- *language*-ci: counts number of repositories of *language* that use ci/cd
Result topics:
- persistent://public/static/languages: keeps track of unique languages
- persistent://public/static/language_results: aggregated information of each language
"""

from pulsar import Function

class AggregateFunction(Function):
    def __init__(self):
        self.tenant = 'public'
        self.namespace = 'static'

    # This function gets called each time a day is published in
    # the topic: persistent://public/static/days_processed
    def process(self, item, context):
        logger = context.get_logger()
        logger.info(f"\n*** Message Content: {item}")
        logger.info(f"*** In topic: {context.get_current_message_topic_name()}")
        
        in_topic = context.get_current_message_topic_name()
        if 'basic_repo_info' in in_topic:
            # basic_repo_info: (repo_id, 'owner', 'name', 'language')
            message = eval(item) # convert byte to text, and then to tuple
            repo_id = str(message[0])            
            context.incr_counter(f'{repo_id}', 1) # register we've reviewed repo_id
            if (context.get_counter(f'{repo_id}') == 1):
                # Increase the language counter if the repo hasn't been processed before
                language_repos = f"{message[3]}-repos"
                context.incr_counter(f'{language_repos}', 1)
                if (context.get_counter(f'{language_repos}') == 1):
                    # If its the first time we see the language publish it to 'languages' topic
                    context.publish(
                        topic_name=f"persistent://{self.tenant}/{self.namespace}/languages",
                        message=(message[3]).encode('utf-8'))
        elif 'repo_with_tests' in in_topic:
            message = eval(item)
            repo_id = str(message[0])
            # repo_with_tests: (repo_id, 'language')
            repo_id_tests = f"{repo_id}-tests"
            context.incr_counter(f'{repo_id_tests}', 1)
            if (context.get_counter(f'{repo_id_tests}') == 1):
                # Increase counter if the repo hasn't been processed before for tests
                language_tests = f"{message[1]}-tests"
                context.incr_counter(f'{language_tests}', 1)
        elif 'repo_with_ci' in in_topic:
            message = eval(item)
            repo_id = str(message[0])
            # repo_wit_ci: (repo_id, 'language')
            # This time there's no need to check if the repo has been processed multiple times
            language_ci = f"{message[1]}-ci"
            context.incr_counter(f'{language_ci}', 1)
        elif 'aggregate_languages_info' in in_topic:
            language = item
            num_repos = context.get_counter(f"{language}-repos")
            num_tests = context.get_counter(f"{language}-tests")
            num_cis = context.get_counter(f"{language}-ci")
            # Create a tuple with all info to publish
            # ('language', num_repos, num_tests, num_cis)
            lang_tuple = f"('{language}', {num_repos}, {num_tests}, {num_cis})"
            context.publish(
                topic_name=f"persistent://{self.tenant}/{self.namespace}/language_results",
                message=(lang_tuple).encode('utf-8'))