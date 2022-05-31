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

Topics in public/default namespace (doesn't retain messages):
persistent://public/default/basic_repo_info
persistent://public/default/repo_with_tests
persistent://public/default/day_to_process

Topics in public/static namespace (retains messages):
persistent://public/static/initialized
persistent://public/static/days_processed
persistent://public/static/free_token
persistent://public/static/commit_repo_info
persistent://public/static/repo_with_ci

persistent://public/static/*YYYY-MM-DD*_partial_result_commit
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
        self.commits = repo_tuple[1]
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
        
    def _set_init_status(self):
        """ Identifying the status based on messages of 'initialized' topic.
        If there are no messages its because it hasn't been initialized.
        A first 'Initializing' message is because its starting, and a second
        'Initialized' message is because it has already started
        """
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
        self.load_all_git_tokens() # Loads 4 tokens in 'free_token'
        
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
        ‘YYYY-MM-DD’ format). Useful to compute partial ‘global’ results every
        certain time by Pulsar Functions. """
        try:
            topic_name = 'days_processed'
            days_processed_producer = self.client.create_producer(
                topic=f'persistent://{self.tenant}/{self.static_namespace}/{topic_name}',
                producer_name=f'{topic_name}_prod',
                message_routing_mode=PartitionsRoutingMode.UseSinglePartition)
        except Exception as e:
            print(f"\n*** Exception creating 'days_processed' topic: {e} ***\n")
            days_processed_producer.close()
            return
       
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
        """ Flush tokens in 'free_token' and 'standby_token' and load all
        again in 'free_token' """
        
        while True:
            token = self.get_free_token()
            if token == None: break
        
        # while True:            
            #token = self.get_standby_token()
            #if token == None: break
            
        token_list = [token.split("#")[0].strip() for token in open(
            "tokens.txt", "r").readlines()]
        
        for token in token_list:
            self.put_free_token(token)
            
        return True
    
    def create_day_to_process(self):
        """ Create the 'day_to_process' topic with 365 'YYYY-MM-DD' values.
        To be called automatically while initializing, but also making it externally
        available for test purposes """
        print("\n*** Populating 'day_to_process' topic ***\n")
        try:
            topic_name = 'day_to_process'
            day_producer = self.client.create_producer(
                topic=f'persistent://{self.tenant}/{self.namespace}/{topic_name}',
                message_routing_mode=PartitionsRoutingMode.UseSinglePartition)
        except Exception as e:
            print(f"\n*** Exception creating 'day_to_process' topic: {e} ***\n")
            day_producer.close()
            return
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
        """ Pops a ‘YYYY-MM-DD’ string value from the topic 'day_to_process'.
        If there are no more days to process, returns None (Null) """
        if self.last_day_processed: return None
    
        topic_name = 'day_to_process'
        # Create a consumer on persistent topic, always using the same name,
        # so it always references to the current read position
        try:
            day_consumer = self.client.subscribe(
                topic=f"persistent://{self.tenant}/{self.namespace}/{topic_name}",
                subscription_name=f'{topic_name}_sub',
                initial_position=_pulsar.InitialPosition.Earliest)
        except Exception as e:
            print(f"\n*** Exception creating day_consumer: {e} ***\n")
            day_consumer.close()
            return
            
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
        
        day_of_year = int(datetime.datetime.strptime(day, '%Y-%m-%d').strftime('%j'))
        if (day_of_year%self.days_to_review == 0):
            self.process_partial_results(day)
        
        # If we reached the end, signal so we start sending None from next call on
        if day == '2021-12-31':
            self.last_day_processed = True
        
        # Close at the end so no to block other processes that use the same subscription
        day_consumer.close()
        
        self._put_days_processed(day)
        
        return day
            
    def get_initializing(self):
        return self.initializing
    
    def get_initialized(self):
        return self.initialized
    
    def put_free_token(self, token):
        """ Posts a token id string with available quota """
        try:
            topic_name = 'free_token'
            free_token_producer = self.client.create_producer(
                topic=f'persistent://{self.tenant}/{self.static_namespace}/{topic_name}',
                producer_name=f'{topic_name}_prod',
                message_routing_mode=PartitionsRoutingMode.UseSinglePartition)
        except Exception as e:
            print(f"\n*** Exception creating 'free_token' topic: {e} ***\n")
            free_token_producer.close()
            return
       
        try:
            free_token_producer.send((
                f"{token}").encode('utf-8'))      
        except Exception as e:
            print(f"\n*** Exception sending date message: {e} ***\n")
            free_token_producer.close()
            return
            
        free_token_producer.close()        
        return True
    
    def get_free_token(self):
        """ pops the string of an available token """
        topic_name = 'free_token'
        try:
            free_token_consumer = self.client.subscribe(
                topic=f"persistent://{self.tenant}/{self.static_namespace}/{topic_name}",
                subscription_name=f'{topic_name}_sub',
                initial_position=_pulsar.InitialPosition.Earliest)
        except Exception as e:
            print(f"\n*** Exception creating free_token_consumer: {e} ***\n")
            free_token_consumer.close()
            return None
        
        try:
            # Give up to half a second to receive an answer
            msg = free_token_consumer.receive(timeout_millis=500)
            # Save the string message (decode from byte value)
            token = str(msg.value().decode())
            # Acknowledge that the message was received          
            free_token_consumer.acknowledge(msg)
        except Exception as e:
            print(f"\n*** Exception receiving value from 'free_token_consumer': {e} ***")
            print("Might have run out of free tokens\n")
            free_token_consumer.close()
            return None
        
        free_token_consumer.close()
        return token
    
    def put_standby_token(self, token):
        """ posts a token id string from a token with exhausted quota """
        topic_name = 'standby_token'
        try:
            standby_token_producer = self.client.create_producer(
                topic=f'persistent://{self.tenant}/{self.static_namespace}/{topic_name}',
                producer_name=f'{topic_name}_prod',
                message_routing_mode=PartitionsRoutingMode.UseSinglePartition)
        except Exception as e:
            print(f"\n*** Exception creating 'standby_token' topic: {e} ***\n")
            standby_token_producer.close()
            return
       
        try:
            standby_token_producer.send((
                f"{token}").encode('utf-8'))      
        except Exception as e:
            print(f"\n*** Exception sending standby_token message: {e} ***\n")
            standby_token_producer.close()
            return
            
        standby_token_producer.close()
        return True

    def get_standby_token(self):
        """  pops the string of a standby token """
        topic_name = 'standby_token'
        try:
            standby_token_consumer = self.client.subscribe(
                topic=f"persistent://{self.tenant}/{self.static_namespace}/{topic_name}",
                subscription_name=f'{topic_name}_sub',
                initial_position=_pulsar.InitialPosition.Earliest)
        except Exception as e:
            print(f"\n*** Exception creating standby_token_consumer: {e} ***\n")
            standby_token_consumer.close()
            return None
        
        try:
            # Give up to half a second to receive an answer
            msg = standby_token_consumer.receive(timeout_millis=500)
            # Save the string message (decode from byte value)
            token = str(msg.value().decode())
            # Acknowledge that the message was received          
            standby_token_consumer.acknowledge(msg)
        except Exception as e:
            print(f"\n*** Exception receiving value from 'standby_token_consumer': {e} ***")
            print("Might have run out of standby tokens\n")
            standby_token_consumer.close()
            return None
        
        standby_token_consumer.close()
        return token
    
    def put_basic_repo_info(self, repo_list):
        """ Publishes a series of (repo_id, 'owner', 'name', 'language') tuples in the
        'repos_for_commit_count' and 'repos_for_test_check' topics. The same info gets
        published in the two places to make the processing easier"""
        
        # Start publishing the info in 'repos_for_commit_count'
        try:
            topic_name = 'repos_for_commit_count'
            repos_for_commit_producer = self.client.create_producer(
                topic=f'persistent://{self.tenant}/{self.namespace}/{topic_name}',
                producer_name=f'{topic_name}_prod',
                message_routing_mode=PartitionsRoutingMode.UseSinglePartition)
        except Exception as e:
            print(f"\n*** Exception creating 'repos_for_commit_count' topic: {e} ***\n")
            repos_for_commit_producer.close()
            return
        
        for repo in repo_list:
            try:
                repos_for_commit_producer.send((
                    f"({repo[0]}, '{repo[1]}', '{repo[2]}', '{repo[3]}')").encode('utf-8'))      
            except Exception as e:
                print(f"\n*** Exception sending 'repos_for_commit_count' message: {e} ***\n")
                repos_for_commit_producer.close()
                return            
        repos_for_commit_producer.close()
        
        # Now publish the same info in 'repos_for_commit_count'
        try:
            topic_name = 'repos_for_test_check'
            repos_for_test_producer = self.client.create_producer(
                topic=f'persistent://{self.tenant}/{self.namespace}/{topic_name}',
                producer_name=f'{topic_name}_prod',
                message_routing_mode=PartitionsRoutingMode.UseSinglePartition)
        except Exception as e:
            print(f"\n*** Exception creating 'repos_for_test_check' topic: {e} ***\n")
            repos_for_test_producer.close()
            return
        
        for repo in repo_list:
            try:
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
        try:
            repos_for_commit_consumer = self.client.subscribe(
                topic=f"persistent://{self.tenant}/{self.namespace}/{topic_name}",
                subscription_name=f'{topic_name}_sub',
                initial_position=_pulsar.InitialPosition.Earliest)
        except Exception as e:
            print(f"\n*** Exception creating basic_repo_info: {e} ***\n")
            repos_for_commit_consumer.close()
            return
        
        repo_list = []
        for i in range(num_repos):
            try:
                # Give up to 3 seconds to receive an answer
                msg = repos_for_commit_consumer.receive(timeout_millis=3000)
                # Save the string message (decode from byte value)
                message = str(msg.value().decode())
                # Process message and append to repo_list
                repo_list.append(eval(message))
                # Acknowledge that the message was received          
                repos_for_commit_consumer.acknowledge(msg)
            except Exception as e:
                print(f"\n*** Exception receiving value from 'repos_for_commit_count': {e} ***")
                print("Might have reached the limit of available repos in the topic\n")
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
        try:
            repos_for_test_check_consumer = self.client.subscribe(
                topic=f"persistent://{self.tenant}/{self.namespace}/{topic_name}",
                subscription_name=f'{topic_name}_sub',
                initial_position=_pulsar.InitialPosition.Earliest)
        except Exception as e:
            print(f"\n*** Exception creating basic_repo_info: {e} ***\n")
            repos_for_test_check_consumer.close()
            return
        
        repo_list = []
        for i in range(num_repos):
            try:
                # Give up to 3 seconds to receive an answer
                msg = repos_for_test_check_consumer.receive(timeout_millis=3000)
                # Save the string message (decode from byte value)
                message = str(msg.value().decode())
                # Process message and append to repo_list
                repo_list.append(eval(message))
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
        try:
            topic_name = 'commit_repo_info'
            commit_repo_producer = self.client.create_producer(
                topic=f'persistent://{self.tenant}/{self.static_namespace}/{topic_name}',
                producer_name=f'{topic_name}_prod',
                message_routing_mode=PartitionsRoutingMode.UseSinglePartition)
        except Exception as e:
            print(f"\n*** Exception creating 'commit_repo_info' topic: {e} ***\n")
            commit_repo_producer.close()
            return
        
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
        """ Publishes a series of (repo_id, 'language') tuples in the
        repo_with_tests topic """
        try:
            topic_name = 'repo_with_tests'
            repo_with_tests_producer = self.client.create_producer(
                topic=f'persistent://{self.tenant}/{self.namespace}/{topic_name}',
                producer_name=f'{topic_name}_prod',
                message_routing_mode=PartitionsRoutingMode.UseSinglePartition)
        except Exception as e:
            print(f"\n*** Exception creating 'repo_with_tests' topic: {e} ***\n")
            repo_with_tests_producer.close()
            return
        
        for repo in repo_list:
            try:
                repo_with_tests_producer.send((
                    f"({repo[0]}, '{repo[1]}')").encode('utf-8'))      
            except Exception as e:
                print(f"\n*** Exception sending repo_with_tests message: {e} ***\n")
                repo_with_tests_producer.close()
                return
            
        repo_with_tests_producer.close()
        return True
    
    def get_repo_with_tests(self, num_repos):
        """  pops a num_repos sized list with (repo_id, 'language') tuples
        from the topic repo_with_tests. Might have less elements if the
        topic doesn't has more repos to return """
        # Create a consumer on persistent topic, always using the same name,
        # so it always references to the current read position
        topic_name = 'repo_with_tests'
        try:
            repo_with_tests_consumer = self.client.subscribe(
                topic=f"persistent://{self.tenant}/{self.namespace}/{topic_name}",
                subscription_name=f'{topic_name}_sub',
                initial_position=_pulsar.InitialPosition.Earliest)
        except Exception as e:
            print(f"\n*** Exception creating repo_with_tests: {e} ***\n")
            repo_with_tests_consumer.close()
            return
        
        repo_list = []
        for i in range(num_repos):
            try:
                # Give up to 3 seconds to receive an answer
                msg = repo_with_tests_consumer.receive(timeout_millis=3000)
                # Save the string message (decode from byte value)
                message = str(msg.value().decode())
                # Process message and append to repo_list
                repo_list.append(eval(message))
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
        try:
            topic_name = 'repo_with_ci'
            repo_with_ci_producer = self.client.create_producer(
                topic=f'persistent://{self.tenant}/{self.static_namespace}/{topic_name}',
                producer_name=f'{topic_name}_prod',
                message_routing_mode=PartitionsRoutingMode.UseSinglePartition)
        except Exception as e:
            print(f"\n*** Exception creating 'repo_with_ci_producer' topic: {e} ***\n")
            repo_with_ci_producer.close()
            return
        
        for repo in repo_list:
            try:
                repo_with_ci_producer.send((
                    f"({repo[0]}, '{repo[1]}')").encode('utf-8'))      
            except Exception as e:
                print(f"\n*** Exception sending 'repo_with_ci_producer' message: {e} ***\n")
                repo_with_ci_producer.close()
                return
            
        repo_with_ci_producer.close()
        return True
    
    def process_partial_results(self, cutoff_date):
        """ Process partial answers up to existing information and publish top
        repos by commit number to a special result topic """
        # Walk through current list of languages, and send them to 'aggregate_languages_info'
        # topic to signal Pulsar Functions to report current counters
        languages_topic = 'languages'
        curr_time = str(int(time.time()))
        try:
            reader = self.client.create_reader(
                topic=f"persistent://{self.tenant}/{self.static_namespace}/{languages_topic}",
                reader_name=f'{languages_topic}_sub_{curr_time}',
                start_message_id=MessageId.earliest)
        except Exception as e:
            print(f"\n*** Exception creating reader for 'languages' topic: {e} ***\n")
            reader.close()
            return        

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
        try:
            lang_result_topic = 'aggregate_languages_info'
            lang_result_producer = self.client.create_producer(
                topic=f'persistent://{self.tenant}/{self.static_namespace}/{lang_result_topic}',
                producer_name=f'{lang_result_topic}_prod',
                message_routing_mode=PartitionsRoutingMode.UseSinglePartition)
        except Exception as e:
            print(f"\n*** Exception creating 'aggregate_languages_info' topic: {e} ***\n")
            lang_result_producer.close()
            return
        
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
        try:
            reader = self.client.create_reader(
                topic=f"persistent://{self.tenant}/{self.static_namespace}/{topic_name}",
                reader_name=f'{topic_name}_sub_{curr_time}',
                start_message_id=MessageId.earliest)
        except Exception as e:
            print(f"\n*** Exception creating reader for commit_repo_info: {e} ***\n")
            reader.close()
            return
        
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
                # Only add on list if bigger than lower_value
                if (repo_tuple[1] > lower_value):
                    ord_list.add(RepoCommits(repo_tuple))
                    # When exceeding size, take last element and update lower_value
                    if (len(ord_list) > self.top_repos_partial_results):
                        lower_value = ord_list.pop()[1]
            except Exception as e:
                print(f"\n*** Exception receiving value from 'commit_repo_info': {e} ***\n")
                break      
        reader.close()
        
        # Now publish the results in a {cutoff_date}_partial_result_commit topic
        try:
            topic_name = f'{cutoff_date}_partial_result_commit'
            partial_result_commit_producer = self.client.create_producer(
                topic=f'persistent://{self.tenant}/{self.static_namespace}/{topic_name}',
                producer_name=f'{topic_name}_prod',
                message_routing_mode=PartitionsRoutingMode.UseSinglePartition)
        except Exception as e:
            print(f"\n*** Exception creating '{cutoff_date}_partial_result_commit' topic: {e} ***\n")
            partial_result_commit_producer.close()
            return
        
        for repo in ord_list.irange():
            try:
                partial_result_commit_producer.send((
                    f"({repo.ident}, {repo.commits}, '{repo.owner}', '{repo.repo_name}')").encode('utf-8'))
            except Exception as e:
                print(f"\n*** Exception sending basic_repo_info message: {e} ***\n")
                partial_result_commit_producer.close()
                return
            
        partial_result_commit_producer.close()      
        
        return True

    
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



my_pulsar.process_partial_results('2021-01-29')

my_pulsar.close()
"""