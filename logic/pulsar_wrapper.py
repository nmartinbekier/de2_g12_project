"""
Requires pulsar-client: pip install pulsar-client==2.10.0
Requires sortedcontainers: pip install sortedcontainers

For this script to work, requires having a Pulsar Standalone receiving connections in port:6650
If Pulsar server is not in localhost, instantiate the class with the IP its running on. For
ex: my_pulsar = pulsar_wrapper.PulsarConnection(ip_address=192.168.##.##)

Pulsar namespaces also have to be configured so topics behave as they are intended below.
The following commands are needed for this, using pulsar-admin command line:
$bin/pulsar-admin namespaces set-retention public/default --size -1 --time -1
$bin/pulsar-admin namespaces set-deduplication public/default --enable
$bin/pulsar-admin namespaces create public/static
$bin/pulsar-admin namespaces set-retention public/static --size -1 --time -1
$bin/pulsar-admin namespaces set-deduplication public/static --enable

Also, the Pulsar Function service also has to be started for this to work.
Instructions for the command line instruction to start it are in 'aggregate_functions.py'

This script uses the following topics. They can be listed, examined or deleted using
'bin/pulsar-admin topics' commands

Topics in public/default namespace:
persistent://public/default/repos_for_commit_count
persistent://public/default/repos_for_test_check
persistent://public/default/repo_with_tests
persistent://public/default/day_to_process

Topics in public/static namespace (retains messages):
persistent://public/static/initialized
persistent://public/static/days_processed
persistent://public/static/free_token
persistent://public/static/commit_repo_info
persistent://public/static/repo_with_ci

persistent://public/static/*YYYY-MM-DD*_result_commit
persistent://public/static/aggregate_languages_info : signals Pulsar to compute results for this language
persistent://public/static/languages : list of unique languages
persistent://public/static/language_results : posts aggregated information of each language in tuples
of the form: ('language', num_repos, num_tests, num_ci)

"""
import requests
import datetime
import time
import bisect
import pulsar
from pulsar import PartitionsRoutingMode
from pulsar import MessageId
import _pulsar
import sortedcontainers

class RepoCommits(object):
    """ Data Type to support tuple in-place sorting using sortedcontainers """
    def __init__(self, repo_tuple):
        self.ident = repo_tuple[0]
        self.commits = int(repo_tuple[1] or 0)
        self.owner = repo_tuple[2]
        self.repo_name = repo_tuple[3]
        
    def __repr__(self):
        return f"({self.ident}, {self.commits}, '{self.owner}', '{self.repo_name}')"

class PulsarConnection:

    def __init__(self, ip_address='localhost'):
        self.client = pulsar.Client(f'pulsar://{ip_address}:6650')
        self.tenant = 'public'
        self.namespace = 'default'
        self.static_namespace = 'static'
        self.initializing = False
        self.initialized = False
        self.token_list = None
        self.current_token = 1
        self.last_day_processed = False
        self.days_to_review = 15 # Lapse of days to make an update on partial results
        self.top_repos_partial_results = 100 # Top commited repositories to publish in partial results
        self._set_init_status() # updates 'initialized' and 'initializing'
        # Initialize the system if it hasn't
        if not self.initialized:
            self._initialize_pulsar()
    
    def close(self):
        """ Remeber to close when finished working """
        try: self.client.close()
        except Exception as e: print(f"\n*** Exception: {e} ***\n")
        
    def eval_message(self, message):
        """ Check the message can be evaluated """
        try:
            processed_message = eval(message)
        except:
            processed_message = False
        return processed_message
        
    def _set_init_status(self):
        """ Identifying the status based on messages of 'initialized' topic.
        If there are no messages its because it hasn't been initialized.
        A first 'Initializing' message is because its starting, and a second
        'Initialized' message is because it has already started
        """
        
        # Load tokens (workaround to loading them through Pulsar)
        self.token_list = [token.split("#")[0].strip() for token in open(
            "tokens.txt", "r").readlines()]
        
        try:
            has_messages = False
            curr_time = str(int(time.time()))
            topic_name = 'initialized'
            reader = self.client.create_reader(
                topic=f'persistent://{self.tenant}/{self.static_namespace}/{topic_name}',
                reader_name=topic_name+'_read_'+curr_time,
                start_message_id=MessageId.earliest)
            has_messages = reader.has_message_available()
        except Exception as e: print(f"\n*** Exception: {e} ***\n")
        # If there are no messages, it hasn't been initialized
        if not has_messages:
            print("\nIt seems the system needs initializing\n")
            reader.close()
            return
    
        # Check now if it is initializing
        msg = reader.read_next()
        message = str(msg.value().decode())
        if message == "Initializing":
            print("Found 'Initializing' message")
            self.initializing = True
        else:
            print("Didn't found 'Initializing' message")
        
        # Check if it has already initialized
        try:
            msg = reader.read_next(timeout_millis=3000)
            message = str(msg.value().decode())
        except Exception as e:
            print(f"\n*** Didn't found 'Initialized' message : {e} ***\n")
            
        if message == "Initialized":
            print("Found 'Initialized' message")
            self.initialized = True
            self.initializing = False
        reader.close()
        
        return True

    def _initialize_pulsar(self):
        """ Initialize relevant topics: 'initialized', 'days_processed' """
        
        # If its initilizing elsewhere, wait until it has finished
        while self.initializing:
            print("\nThe system is initializing elsewhere, checking again in 5 seconds..\n")
            time.sleep(5)
            self._set_init_status()
            
        
        # Send an Initializing message, so other workers don't do the same
        print("\n*** Initializing the system *** \n")
        try:
            curr_time = str(int(time.time()))
            topic_name = 'initialized'
            init_producer = self.client.create_producer(
                topic=f'persistent://{self.tenant}/{self.static_namespace}/{topic_name}',
                producer_name=f'{topic_name}_prod_{curr_time}',
                message_routing_mode=PartitionsRoutingMode.UseSinglePartition)
        except Exception as e:
            print(f"\n*** Exception: {e} ***\n")
            init_producer.close()
            return
        
        try:
            init_producer.send(("Initializing").encode('utf-8'))      
        except Exception as e:
            print(f"\n*** Exception sending Initializing message: {e} ***\n")
            init_producer.close()
            return
        
        self.initializing = True
            
        self.create_day_to_process() # Creates 365 days in 'day_to_process' topic
        #self.load_all_git_tokens() # Loads 4 tokens in 'free_token'
        
        try:
            init_producer.send(("Initialized").encode('utf-8'))      
        except Exception as e:
            print(f"\n*** Exception sending Initialized message: {e} ***\n")
            init_producer.close()
            return
        init_producer.close()
        
        self.initializing = False
        self.initialized = True
        print("\n*** The system has been initialized. Now get working! ***\n")
        
        return True    
    
    def _put_days_processed(self, day):
        """ Keeps track of which days have been processed so far (each day with a
        ???YYYY-MM-DD??? format). Useful to compute partial ???global??? results every
        certain time by Pulsar Functions. """
        while True:
            try:
                topic_name = 'days_processed'
                days_processed_producer = self.client.create_producer(
                    topic=f'persistent://{self.tenant}/{self.static_namespace}/{topic_name}',
                    producer_name=f'{topic_name}_prod',
                    message_routing_mode=PartitionsRoutingMode.UseSinglePartition)
                break
            except Exception as e:
                print(f"\n*** Exception creating 'days_processed' topic: {e} ***\n")
                print("Retrying in 1 second")
                time.sleep(1)
       
        try:
            days_processed_producer.send((
                f"{day}").encode('utf-8'))      
        except Exception as e:
            print(f"\n*** Exception sending date message: {e} ***\n")
            days_processed_producer.close()
            return
            
        days_processed_producer.close()        
        return True
        
    def load_all_git_tokens(self):
        """ Updated: now just using a token list """
            
        return True
    
    def create_day_to_process(self):
        """ Create the 'day_to_process' topic with 365 'YYYY-MM-DD' values.
        To be called automatically while initializing, but also making it externally
        available for test purposes """
        print("\n*** Populating 'day_to_process' topic ***\n")
        while True:
            try:
                topic_name = 'day_to_process'
                day_producer = self.client.create_producer(
                    topic=f'persistent://{self.tenant}/{self.namespace}/{topic_name}',
                    message_routing_mode=PartitionsRoutingMode.UseSinglePartition)
                break
            except Exception as e:
                print(f"\n*** Exception creating 'day_to_process' topic: {e} ***\n")
                print("Waiting 1 second..")
                time.sleep(1)
        
        init_date = datetime.datetime(2021, 1, 1)
        dates = [(init_date + datetime.timedelta(days=idx)).strftime('%Y-%m-%d') for idx in range(365)]
        
        for date in dates:
            try:
                day_producer.send((f"{date}").encode('utf-8'))      
            except Exception as e:
                print(f"\n*** Exception sending date message: {e} ***\n")
                day_producer.close()
                return
        day_producer.close()
        return True
    
    def get_day_to_process(self):
        """ Pops a ???YYYY-MM-DD??? string value from the topic 'day_to_process'.
        If there are no more days to process, returns None (Null) """
        if self.last_day_processed: return None
        
        topic_name = 'day_to_process'
        # Create a consumer on persistent topic, always using the same name,
        # so it always references to the current read position
        while True:
            try:
                day_consumer = self.client.subscribe(
                    topic=f"persistent://{self.tenant}/{self.namespace}/{topic_name}",
                    subscription_name=f'{topic_name}_sub',
                    initial_position=_pulsar.InitialPosition.Earliest)
                break
            except Exception as e:
                print(f"\n*** Exception creating day_consumer: {e} ***\n")
                print(f"Waiting 1 secs until its liberated")
                time.sleep(1)
                #day_consumer.close()
            
        try:
            msg = day_consumer.receive()
            # Save the string message (decode from byte value)
            day = str(msg.value().decode())
            # Acknowledge that the message was received          
            day_consumer.acknowledge(msg)
        except Exception as e:
            print(f"\n*** Exception receiving value from 'day_consumer': {e} ***\n")
            day_consumer.close()
            return
        
        # If we reached the end, signal so we start sending None from next call on
        if day == '2021-12-31':
            self.last_day_processed = True
        
        # Every 'self.days_to_review' days, compute partial results
        if (self.last_day_processed == False):
            day_of_year = int(datetime.datetime.strptime(day, '%Y-%m-%d').strftime('%j'))
            if (day_of_year%self.days_to_review == 0):
                self.process_results(day)
        
        # Close at the end so no to block other processes that use the same subscription
        day_consumer.close()
        
        self._put_days_processed(day)
        
        return day
            
    def get_initializing(self):
        return self.initializing
    
    def get_initialized(self):
        return self.initialized
    
    def put_free_token(self, token):
        """ Updated: now not using Pulsar for topic management.
        Now only iterating through list """        
        return True
    
    
    def get_free_token(self):
        """ Updated version: takes the next token from self.token_list """
        token = self.token_list[self.current_token]
        self.current_token = (self.current_token+1)%len(self.token_list)
        return token
    
    def put_standby_token(self, token):
        """ Updated: now not using Pulsar for topic management.
        Now only iterating through list """   
        return True

    def get_standby_token(self):
        """ Updated: now not using Pulsar for topic management.
        Now only iterating through list """   
        return self.get_free_token()
    
    def show_token_status(self):
        """ Just checks how the status of the free and standby tokens are currently.
        Returns a tuple with two lists ( [free_tokens], [standby_tokens] ) """
        try:
            curr_time = str(int(time.time()))
            topic_name = 'free_token'
            reader = self.client.create_reader(
                topic=f'persistent://{self.tenant}/{self.static_namespace}/{topic_name}',
                reader_name=topic_name+'_read_'+curr_time,
                start_message_id=MessageId.earliest)
            has_messages = reader.has_message_available()
        except Exception as e: print(f"\n*** Exception: {e} ***\n")
        if not has_messages:
            print("\nIt seems there is no information of free tokens\n")
            reader.close()
            return
        
        free_token_list = []
        while reader.has_message_available():
            try:
                # Give up to 600 milliseconds to receive an answer
                msg = reader.read_next(timeout_millis=600)
                # Save the string message (decode from byte value)
                free_token_list.append(str(msg.value().decode()))
            except Exception as e:
                print(f"\n*** Exception checking for info from 'free_token' topic: {e} ***\n")
                break
        reader.close()

        try:
            curr_time = str(int(time.time()))
            topic_name = 'standby_token'
            reader = self.client.create_reader(
                topic=f'persistent://{self.tenant}/{self.static_namespace}/{topic_name}',
                reader_name=topic_name+'_read_'+curr_time,
                start_message_id=MessageId.earliest)
            has_messages = reader.has_message_available()
        except Exception as e: print(f"\n*** Exception: {e} ***\n")
        if not has_messages:
            print("\nIt seems there is no information of standby tokens\n")
            reader.close()
            return
        
        standby_token_list = []
        while reader.has_message_available():
            try:
                # Give up to 600 milliseconds to receive an answer
                msg = reader.read_next(timeout_millis=600)
                # Save the string message (decode from byte value)
                standby_token_list.append(str(msg.value().decode()))
            except Exception as e:
                print(f"\n*** Exception checking for info from 'standby_token' topic: {e} ***\n")
                break
        reader.close()
        return ( (free_token_list, standby_token_list) )
    
    def put_basic_repo_info(self, repo_list):
        """ Publishes a series of (repo_id, 'owner', 'name', 'language') tuples in the
        'repos_for_commit_count' and 'repos_for_test_check' topics. The same info gets
        published in the two places to make the processing easier"""
        
        # Start publishing the info in 'repos_for_commit_count'
        while True:
            try:
                topic_name = 'repos_for_commit_count'
                repos_for_commit_producer = self.client.create_producer(
                    topic=f'persistent://{self.tenant}/{self.namespace}/{topic_name}',
                    producer_name=f'{topic_name}_prod',
                    message_routing_mode=PartitionsRoutingMode.UseSinglePartition)
                break
            except Exception as e:
                print(f"\n*** Exception creating 'repos_for_commit_count' topic: {e} ***\n")
                print("Retrying in 1 second")
                time.sleep(1)
                #repos_for_commit_producer.close()
        
        for repo in repo_list:
            try:
                # Remove apostrophes
                repo = list(repo)
                for count, value in enumerate(repo):
                    if isinstance(value, str): repo[count] = value.replace("'", "")
                repos_for_commit_producer.send((
                    f"({repo[0]}, '{repo[1]}', '{repo[2]}', '{repo[3]}')").encode('utf-8'))      
            except Exception as e:
                print(f"\n*** Exception sending 'repos_for_commit_count' message: {e} ***\n")
                repos_for_commit_producer.close()
                return            
        repos_for_commit_producer.close()
        
        # Now publish the same info in 'repos_for_commit_count'
        while True:
            try:
                topic_name = 'repos_for_test_check'
                repos_for_test_producer = self.client.create_producer(
                    topic=f'persistent://{self.tenant}/{self.namespace}/{topic_name}',
                    producer_name=f'{topic_name}_prod',
                    message_routing_mode=PartitionsRoutingMode.UseSinglePartition)
                break
            except Exception as e:
                print(f"\n*** Exception creating 'repos_for_test_check' topic: {e} ***\n")
                print("Retrying in 1 second")
                time.sleep(1)
        
        for repo in repo_list:
            try:
                # Remove apostrophes
                repo = list(repo)
                for count, value in enumerate(repo):
                    if isinstance(value, str): repo[count] = value.replace("'", "")
                repos_for_test_producer.send((
                    f"({repo[0]}, '{repo[1]}', '{repo[2]}', '{repo[3]}')").encode('utf-8'))      
            except Exception as e:
                print(f"\n*** Exception sending 'repos_for_test_check' message: {e} ***\n")
                repos_for_test_producer.close()
                return            
        repos_for_test_producer.close()
        
        return True
    
    def get_repos_for_commit_count(self, num_repos=1):
        """  pops a num_repos sized list with (repo id, 'owner', 'name', language') 
        tuples from the topic 'repos_for_commit_count'. Might have less elements if the
        topic doesn't has more repos to return"""
        # Create a consumer on persistent topic, always using the same name,
        # so it always references to the current read position
        topic_name = 'repos_for_commit_count'
        while True:
            try:
                repos_for_commit_consumer = self.client.subscribe(
                    topic=f"persistent://{self.tenant}/{self.namespace}/{topic_name}",
                    subscription_name=f'{topic_name}_sub',
                    initial_position=_pulsar.InitialPosition.Earliest)
                break
            except Exception as e:
                print(f"\n*** Exception creating basic_repo_info: {e} ***\n")
                print("Waiting 1 seconds to retry")
                time.sleep(1)
        
        repo_list = []
        for i in range(num_repos):
            try:
                # Give up to half a second to receive an answer
                msg = repos_for_commit_consumer.receive(timeout_millis=500)
                # Save the string message (decode from byte value)
                message = str(msg.value().decode())
                message = self.eval_message(message)
                # Process message and append to repo_list
                if (message != False): repo_list.append(message)
                # Acknowledge that the message was received          
                repos_for_commit_consumer.acknowledge(msg)
            except Exception as e:
                print(f"\n*** Exception receiving value from 'repos_for_commit_count': {e} ***")
                print("Might have reached the limit of available repos in the topic\n")
                #print(f"Message received: {message}")
                break
        
        repos_for_commit_consumer.close()
        return repo_list

    def get_repos_for_test_check(self, num_repos=1):
        """  pops a num_repos sized list with (repo id, 'owner', 'name', language') 
        tuples from the topic 'repos_for_test_check'. Might have less elements if the
        topic doesn't has more repos to return"""
        # Create a consumer on persistent topic, always using the same name,
        # so it always references to the current read position
        topic_name = 'repos_for_test_check'
        while True:
            try:
                repos_for_test_check_consumer = self.client.subscribe(
                    topic=f"persistent://{self.tenant}/{self.namespace}/{topic_name}",
                    subscription_name=f'{topic_name}_sub',
                    initial_position=_pulsar.InitialPosition.Earliest)
                break
            except Exception as e:
                print(f"\n*** Exception creating basic_repo_info: {e} ***\n")
                print("Waiting 1 secs to retry")
                time.sleep(1)
        
        repo_list = []
        for i in range(num_repos):
            try:
                # Give up to 300 milliseconds to receive an answer
                msg = repos_for_test_check_consumer.receive(timeout_millis=300)
                # Save the string message (decode from byte value)
                message = str(msg.value().decode())
                message = self.eval_message(message)
                # Process message and append to repo_list
                if (message != False): repo_list.append(message)
                # Acknowledge that the message was received          
                repos_for_test_check_consumer.acknowledge(msg)
            except Exception as e:
                print(f"\n*** Exception receiving value from 'repos_for_test_check': {e} ***")
                print("Might have reached the limit of available repos in the topic\n")
                break
        
        repos_for_test_check_consumer.close()
        return repo_list

    def put_commit_repo_info(self, repo_list):
        """ Publishes a series of (repo_id, num_commits, 'repo_owner', 'repo_name') tuples in the
        commit_repo_info topic"""
        while True:
            try:
                topic_name = 'commit_repo_info'
                commit_repo_producer = self.client.create_producer(
                    topic=f'persistent://{self.tenant}/{self.static_namespace}/{topic_name}',
                    producer_name=f'{topic_name}_prod',
                    message_routing_mode=PartitionsRoutingMode.UseSinglePartition)
                break
            except Exception as e:
                print(f"\n*** Exception creating 'commit_repo_info' topic: {e} ***\n")
                print("Waiting 1 sec")
                time.sleep(1)
        
        for repo in repo_list:
            try:
                commit_repo_producer.send((
                    f"({repo[0]}, {repo[1]}, '{repo[2]}', '{repo[3]}')").encode('utf-8'))      
            except Exception as e:
                print(f"\n*** Exception sending commit_repo_info message: {e} ***\n")
                commit_repo_producer.close()
                return
            
        commit_repo_producer.close()
        return True
    
    def put_repo_with_tests(self, repo_list):
        """ Publishes a series of (repo_id, 'repo_owner', 'repo_name', 'language') tuples in the
        repo_with_tests topic """
        while True:
            try:
                topic_name = 'repo_with_tests'
                repo_with_tests_producer = self.client.create_producer(
                    topic=f'persistent://{self.tenant}/{self.namespace}/{topic_name}',
                    producer_name=f'{topic_name}_prod',
                    message_routing_mode=PartitionsRoutingMode.UseSinglePartition)
                break
            except Exception as e:
                print(f"\n*** Exception creating 'repo_with_tests' topic: {e} ***\n")
                print("Wait 1 sec")
                time.sleep(1)
        
        for repo in repo_list:
            try:
                repo_with_tests_producer.send((
                    f"({repo[0]}, '{repo[1]}', '{repo[2]}', '{repo[3]}' )").encode('utf-8'))      
            except Exception as e:
                print(f"\n*** Exception sending repo_with_tests message: {e} ***\n")
                repo_with_tests_producer.close()
                return
            
        repo_with_tests_producer.close()
        return True
    
    def get_repo_with_tests(self, num_repos):
        """  pops a num_repos sized list with (repo_id, 'repo_owner', 'repo_name', 'language')
        tuples from the topic repo_with_tests. Might have less elements if the
        topic doesn't has more repos to return """
        # Create a consumer on persistent topic, always using the same name,
        # so it always references to the current read position
        topic_name = 'repo_with_tests'
        while True:
            try:
                repo_with_tests_consumer = self.client.subscribe(
                    topic=f"persistent://{self.tenant}/{self.namespace}/{topic_name}",
                    subscription_name=f'{topic_name}_sub',
                    initial_position=_pulsar.InitialPosition.Earliest)
                break
            except Exception as e:
                print(f"\n*** Exception creating repo_with_tests: {e} ***\n")
                print("Waiting 1 sec to retry")
                time.sleep(1)
        
        repo_list = []
        for i in range(num_repos):
            try:
                # Give up to 200 milliseconds to receive an answer
                msg = repo_with_tests_consumer.receive(timeout_millis=200)
                # Save the string message (decode from byte value)
                message = str(msg.value().decode())
                message = self.eval_message(message)
                # Process message and append to repo_list
                if (message != False): repo_list.append(message)
                # Acknowledge that the message was received          
                repo_with_tests_consumer.acknowledge(msg)
            except Exception as e:
                print(f"\n*** Exception receiving value from 'repo_with_tests_consumer': {e} ***")
                print("Might have reached the limit of available repos in the topic\n")
                break
        
        repo_with_tests_consumer.close()
        return repo_list

    def put_repo_with_ci(self, repo_list):
        """ Publishes a series of (repo_id, 'language') tuples in the
        repo_with_ci topic """
        while True:
            try:
                topic_name = 'repo_with_ci'
                repo_with_ci_producer = self.client.create_producer(
                    topic=f'persistent://{self.tenant}/{self.static_namespace}/{topic_name}',
                    producer_name=f'{topic_name}_prod',
                    message_routing_mode=PartitionsRoutingMode.UseSinglePartition)
                break
            except Exception as e:
                print(f"\n*** Exception creating 'repo_with_ci_producer' topic: {e} ***\n")
                print("Waiting 1 sec")
                time.sleep(1)
        
        for repo in repo_list:
            try: # repo[3] has the language
                repo_with_ci_producer.send((
                    f"({repo[0]}, '{repo[3]}')").encode('utf-8'))      
            except Exception as e:
                print(f"\n*** Exception sending 'repo_with_ci_producer' message: {e} ***\n")
                repo_with_ci_producer.close()
                return
            
        repo_with_ci_producer.close()
        return True
    
    def process_results(self, cutoff_date='2021-12-31'):
        """ Process answers up to existing information (at cutoff_date) and publish top
        repos by commit number to a special result topic """
        
        # Make sure the final processing hasn't been called before, by checking for a final
        # '2021-12-31' message on the 'initialized' topic
        init_topic = 'initialized'
        curr_time = str(int(time.time()))
        while True:
            try:
                reader = self.client.create_reader(
                    topic=f"persistent://{self.tenant}/{self.static_namespace}/{init_topic}",
                    reader_name=f'{init_topic}_sub_{curr_time}',
                    start_message_id=MessageId.earliest)
                break
            except Exception as e:
                print(f"\n*** Exception creating final reader for 'initialized' topic: {e} ***\n")
                print("Waiting 1 sec")
                time.sleep(1)

        init_list = []
        while reader.has_message_available():
            try:
                # Give up to 600 milliseconds to receive an answer
                msg = reader.read_next(timeout_millis=600)
                # Save the string message (decode from byte value)
                init_list.append(str(msg.value().decode()))
            except Exception as e:
                print(f"\n*** Exception receiving value from final 'initialized' topic: {e} ***\n")
                break
        reader.close()
        
        # If the final day has already been processed, exit the method
        if (init_list[-1] == '2021-12-31'): return False
        
        # Walk through current list of languages, and send them to 'aggregate_languages_info'
        # topic to signal Pulsar Functions to report current counters
        languages_topic = 'languages'
        curr_time = str(int(time.time()))
        while True:
            try:
                reader = self.client.create_reader(
                    topic=f"persistent://{self.tenant}/{self.static_namespace}/{languages_topic}",
                    reader_name=f'{languages_topic}_sub_{curr_time}',
                    start_message_id=MessageId.earliest)
                break
            except Exception as e:
                print(f"\n*** Exception creating reader for 'languages' topic: {e} ***\n")
                print("Waiting 1 sec")
                time.sleep(1)

        language_list = []
        while reader.has_message_available():
            try:
                # Give up to 400 milliseconds to receive an answer
                msg = reader.read_next(timeout_millis=400)
                # Save the string message (decode from byte value)
                language_list.append(str(msg.value().decode()))
            except Exception as e:
                print(f"\n*** Exception receiving value from 'languages': {e} ***\n")
                break
        reader.close()
        
        # Publish current list language to 'aggregate_languages_info'. It will make Pulsar
        # Functions work on them
        while True:
            try:
                lang_result_topic = 'aggregate_languages_info'
                lang_result_producer = self.client.create_producer(
                    topic=f'persistent://{self.tenant}/{self.static_namespace}/{lang_result_topic}',
                    producer_name=f'{lang_result_topic}_prod',
                    message_routing_mode=PartitionsRoutingMode.UseSinglePartition)
                break
            except Exception as e:
                print(f"\n*** Exception creating 'aggregate_languages_info' topic: {e} ***\n")
                print("Wait 1 sec")
                time.sleep(1)
        
        for lang in language_list:
            try:
                lang_result_producer.send((lang).encode('utf-8'))
            except Exception as e:
                print(f"\n*** Exception sending 'aggregate_languages_info' message: {e} ***\n")
                lang_result_producer.close()
                return
        lang_result_producer.close()             
        
        # Create a consumer on persistent topic with the commit information of repos
        # with unique name, so it always start from the beginning
        topic_name = 'commit_repo_info'
        curr_time = str(int(time.time()))
        while True:
            try:
                reader = self.client.create_reader(
                    topic=f"persistent://{self.tenant}/{self.static_namespace}/{topic_name}",
                    reader_name=f'{topic_name}_sub_{curr_time}',
                    start_message_id=MessageId.earliest)
                break
            except Exception as e:
                print(f"\n*** Exception creating reader for commit_repo_info: {e} ***\n")
                print("Wait 1 sec")
                time.sleep(1)
        
        # Ordered list supporting in-place insertion
        ord_list = sortedcontainers.SortedKeyList(key=lambda x: -x.commits)
        lower_value = 0 # Keep track of minimum value from the list
        while reader.has_message_available():
            try:
                # Give up to 400 milliseconds to receive an answer
                msg = reader.read_next(timeout_millis=400)
                # Save the string message (decode from byte value)
                message = str(msg.value().decode())
                repo_tuple = eval(message)     
                # If this is the last time processing results, add all values
                if (cutoff_date=='2021-12-31'):
                    ord_list.add(RepoCommits(repo_tuple))
                else: # Only add on list if bigger than lower_value
                    num_commits = int(repo_tuple[1] or 0)
                    if (num_commits > lower_value):
                        ord_list.add(RepoCommits(repo_tuple))
                        # When exceeding size, take last element and update lower_value
                        if (len(ord_list) > self.top_repos_partial_results):
                            lower_value = ord_list.pop().commits
            except Exception as e:
                print(f"\n*** Exception receiving value from 'commit_repo_info': {e} ***\n")
                break      
        reader.close()
        
        # Now publish the results in a {cutoff_date}_result_commit topic, with tuples in a
        # (id_repo, num_commits, 'repo_owner', 'repo_name') format
        while True:
            try:
                topic_name = f'{cutoff_date}_result_commit'
                result_commit_producer = self.client.create_producer(
                    topic=f'persistent://{self.tenant}/{self.static_namespace}/{topic_name}',
                    producer_name=f'{topic_name}_prod',
                    message_routing_mode=PartitionsRoutingMode.UseSinglePartition)
                break
            except Exception as e:
                print(f"\n*** Exception creating '{cutoff_date}_result_commit' topic: {e} ***\n")
                print("Wait 1 sec")
                time.sleep(1)
        
        for repo in ord_list.irange():
            try:
                result_commit_producer.send((
                    f"({repo.ident}, {repo.commits}, '{repo.owner}', '{repo.repo_name}')").encode('utf-8'))
            except Exception as e:
                print(f"\n*** Exception sending basic_repo_info message: {e} ***\n")
                result_commit_producer.close()
                return            
        result_commit_producer.close()
        
        # Send a message to the 'initialized' topic sharing the cutoff date of the results
        print("\n*** Reporting the cutoff date to the 'initialized' topic *** \n")
        while True:
            try:
                curr_time = str(int(time.time()))
                topic_name = 'initialized'
                init_producer = self.client.create_producer(
                    topic=f'persistent://{self.tenant}/{self.static_namespace}/{topic_name}',
                    producer_name=f'{topic_name}_prod_{curr_time}',
                    message_routing_mode=PartitionsRoutingMode.UseSinglePartition)
                break
            except Exception as e:
                print(f"\n*** Exception sending cutoff date to 'initialized': {e} ***\n")
                print("Wait 1 sec")
                time.sleep(1)
        
        try:
            init_producer.send((f'{cutoff_date}').encode('utf-8'))
        except Exception as e:
            print(f"\n*** Exception sending Initializing message: {e} ***\n")
            init_producer.close()
            return      
        
        init_producer.close()
        return True

    def get_current_cuttoff_date(self):
        """ Receives the 'YYYY-MM-DD' of the last processed information. If 
        it is '2021-12-31' it means all has already been processed """    

        # This info is kept in the 'initialized' topic
        init_topic = 'initialized'
        curr_time = str(int(time.time()))
        while True:
            try:
                reader = self.client.create_reader(
                    topic=f"persistent://{self.tenant}/{self.static_namespace}/{init_topic}",
                    reader_name=f'{init_topic}_sub_{curr_time}',
                    start_message_id=MessageId.earliest)
                break
            except Exception as e:
                print(f"\n*** Exception creating reader for 'initialized' topic: {e} ***\n")
                print("Wait 1 sec")
                time.sleep(1)

        message_list = []
        while reader.has_message_available():
            try:
                # Give up to 400 milliseconds to receive an answer
                msg = reader.read_next(timeout_millis=400)
                # Save the string message (decode from byte value)
                message_list.append(str(msg.value().decode()))
            except Exception as e:
                print(f"\n*** Exception receiving value from 'initialized' topic: {e} ***\n")
                break
        reader.close()

        return message_list[-1]

    def get_top_commits(self, num_values=10):
        """ Function to fetch the top num_values commit results. It assumes messages are
        ordered and in the tuple format: (id_repo, num_commits, 'repo_owner', 'repo_name').
        It returns a num_values list of tuples of the form ('repo_name', num_commits) """

        curr_time = str(int(time.time()))
        cutoff_date = self.get_current_cuttoff_date()

        # Check if there are available results. cutoff_date should have
        # length 10 string ('YYYY-MM-DD')
        if (len(cutoff_date) != 10):
            print(f"\n*** It seems there are still no results. Received '{cutoff_date}' as cutoff value ***\n")
            return

        if (cutoff_date == '2021-12-31'):
            print("\n*** Showing final results (all info has been processed) ***\n")
        else:
            print(f"\n*** Showing partial results up to {cutoff_date} (info is still being processed) ***\n")

        # The results are kept in the {cutoff-date}_result_commit' topic
        topic_name = f"{cutoff_date}_result_commit"
        curr_time = str(int(time.time()))
        while True:
            try:
                reader = self.client.create_reader(
                    topic=f"persistent://{self.tenant}/{self.static_namespace}/{topic_name}",
                    reader_name=f'{topic_name}_sub_{curr_time}',
                    start_message_id=MessageId.earliest)
                break
            except Exception as e:
                print(f"\n*** Exception creating reader for '{cutoff_date}_result_commit' topic: {e} ***\n")
                print("Wait 1 sec")
                time.sleep(1)

        result_list = []
        while (reader.has_message_available() and len(result_list)<num_values):
            try:
                # Give up to 400 milliseconds to receive an answer
                msg = reader.read_next(timeout_millis=700)
                # Save the string message (decode from byte value)
                result_tuple = eval(str(msg.value().decode()))
                repo_name = f"{result_tuple[2]}/{result_tuple[3]}"
                result_list.append((repo_name, result_tuple[1]))
            except Exception as e:
                print(f"\n*** Exception receiving value from '{cutoff_date}_result_commit' topic: {e} ***\n")
                break
        reader.close()

        return result_list    
    
    def get_languages_stats(self):
        """ Receives current aggregated information of languages in a list made of tuples
        ('language', num_repos, num_tests, num_cis). Returns a dictionary with the consolidated
        information, with language as key"""

        curr_time = str(int(time.time()))

        # The results are kept in the 'public/static/language_results' topic
        topic_name = 'language_results'
        curr_time = str(int(time.time()))
        while True:
            try:
                reader = self.client.create_reader(
                    topic=f"persistent://{self.tenant}/{self.static_namespace}/{topic_name}",
                    reader_name=f'{topic_name}_sub_{curr_time}',
                    start_message_id=MessageId.earliest)
                break
            except Exception as e:
                print(f"\n*** Exception creating reader for 'language_results' topic: {e} ***\n")
                print("Wait 1 sec")
                time.sleep(1)

        result_dict = {}
        while reader.has_message_available():
            try:
                # Give up to 400 milliseconds to receive an answer
                msg = reader.read_next(timeout_millis=400)
                # Save the string message (decode from byte value)
                result_tuple = eval(str(msg.value().decode()))
                result_dict[result_tuple[0]]={'num_repos': result_tuple[1],
                                  'num_tests': result_tuple[2],
                                  'num_ci': result_tuple[3]}
            except Exception as e:
                print(f"\n*** Exception receiving value from 'initialized' topic: {e} ***\n")
                break
        reader.close()

        return result_dict
    
"""
# Snippets of test code for playing in python's command line

import pulsar_wrapper
my_pulsar = pulsar_wrapper.PulsarConnection()

print(f"\nStill initializing: {my_pulsar.get_initializing()}")
print(f"Already initialized: {my_pulsar.get_initialized()}\n")

my_pulsar.get_day_to_process()

my_pulsar.put_free_token("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")
token = my_pulsar.get_free_token()

my_pulsar.load_all_git_tokens()

# Test data
repo_list = [
    (7291, '3owner_511', '7repo_511', 'language1'),
    (7292, '3owner_521', '7repo_521', 'language2'),
    (7293, '3owner_531', '7repo_531', 'language3')]
my_pulsar.put_basic_repo_info(repo_list)
my_pulsar.get_repos_for_commit_count(num_repos=2)
my_pulsar.get_repos_for_test_check(num_repos=2)
get_repos_for_test_check(num_repos=2)




    
repos_with_tests_list = [(110, 'Python'),(111, 'C#'),(112, 'Javascript')]
my_pulsar.put_repo_with_tests(repos_with_tests_list)


repos_with_ci_list = [(10, 'Lisp'),(11, 'Java'),(12, 'Go')]
my_pulsar.put_repo_with_ci(repos_with_ci_list)



commit_repo_list = [
    (4, 16, 'owner_1', 'repo_1'),
    (5, 21, 'owner_2', 'repo_2'),
    (6, 26, 'owner_3', 'repo_3')]
my_pulsar.put_commit_repo_info(commit_repo_list)



my_pulsar.process_results('2021-01-01')

my_pulsar.close()
"""