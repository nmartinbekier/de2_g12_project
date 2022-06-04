#!/bin/bash

# Run pulsar in standalone mode as a docker container, exposing the appropriate ports and mounting some dirs
docker run -p 6650:6650  -p 8080:8080 --mount source=pulsardata,target=/pulsar/data --mount source=pulsarconf,target=/pulsar/conf apachepulsar/pulsar:2.9.1 bin/pulsar standalone

# Sleep for a minute to ensure pulsar has started before initializing it. 
# There are probably more efficient ways of knowing when its started though
sleep 1m

# Initialize pulsar with the functions and namespaces required for the producer/consumer
./de2_g12_project/producer/scripts/init-pulsar.sh

# Setup settings for the producer
export pulsar_host=localhost
export debug=false

# Run the producer/consumer
python de2_g12_project/producer/main.py
