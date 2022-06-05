import pulsar
import requests
import os
import json

username = 'OlleDelborg'
token = "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"

client = pulsar.Client('pulsar://localhost:6650')
producer = client.create_producer('Topic')

print("PRODUCER CREATED")

repo = requests.get('https://api.github.com/search/repositories?q=pushed:"2022-05-18"&per_page=1', auth=(username, token))
for i in range(len(repo.json()['items'])):
    # Send a message to consumer
    producer.send('{} {} {}'.format(repo.json()['items'][i]['full_name'], repo.json()['items'][i]['language'], repo.json()['items'][i]['url']).encode('utf-8'))

# Destroy pulsar
client.close()
