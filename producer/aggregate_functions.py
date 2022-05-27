"""
To enable this, it has to be called by pulsar admin:
$ bin/pulsar-admin functions create \
  --py ~/de2_g12_project/producer/aggregate_functions.py \
  --classname aggregate_functions.AggregateFunction \
  --tenant public \
  --namespace static \
  --name aggregate_functions \
  --inputs persistent://public/default/basic_repo_info,persistent://public/default/repo_with_tests,persistent://public/static/repo_with_ci,persistent://public/static/aggregate_languages_info 

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
            message = eval(item.decode()) # convert byte to text, and then to tuple
            repo_id = message(0)
            # basic_repo_info: (repo_id, 'owner', 'name', 'language')
            context.incr_counter(repo_id, 1) # register we've reviewed repo_id
            if (context.get_counter(repo_id) == 1):
                # Increase the language counter if the repo hasn't been processed before
                language_repos = f"{message(3)}-repos"
                context.incr_counter(language_repos, 1)
                if (context.get_counter(language_repos) == 1):
                    # If its the first time we see the language publish it to 'languages' topic
                    context.publish(
                        topic_name=f"persistent://{self.tenant}/{self.namespace}/languages",
                        message=({message(3)}).encode('utf-8'))
        elif 'repo_with_tests' in in_topic:
            message = eval(item.decode())
            repo_id = message(0)
            # repo_with_tests: (repo_id, 'language')
            repo_id_tests = f"{repo_id}-tests"
            context.incr_counter(repo_id_tets, 1)
            if (context.get_counter(repo_id_tests == 1)):
                # Increase counter if the repo hasn't been processed before for tests
                language_tests = f"{message(2)}-tests"
                context.incr_counter(language_tests, 1)
        elif 'repo_with_ci' in in_topic:
            message = eval(item.decode())
            repo_id = message(0)
            # repo_wit_ci: (repo_id, 'language')
            # This time there's no need to check if the repo has been processed multiple times
            language_ci = f"{message(2)}-ci"
            context.incr_counter(language_ci, 1)
        elif 'aggregate_languages_info' in in_topic:
            language = item.decode()
            num_repos = context.get_counter(f"{language}-repos")
            num_tests = context.get_counter(f"{language}-tests")
            num_cis = context.get_counter(f"{language}-ci")
            # Create a tuple with all info to publish
            # ('language', num_repos, num_tests, num_cis)
            lang_tuple = f"('{language}', {num_repos}, {num_tests}, {num_cis})"
            context.publish(
                topic_name=f"persistent://{self.tenant}/{self.namespace}/language_results",
                message=(lang_tuple).encode('utf-8'))