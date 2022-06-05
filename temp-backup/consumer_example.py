import pulsar

# Create a pulsar client by supplying ip address and port
client = pulsar.Client('pulsar://192.168.2.168:6650')

# Subscribe to a topic and create a subscription
consumer = client.subscribe('conv-topic', 'conv-topic-sub')

merged_string = ""

while True:
    msg = consumer.receive()

    try:
        # Save the string message (decode from byte value)
        message = str(msg.value().decode())

        # Acknowledge that the message was received
        consumer.acknowledge(msg)

        # Append each message to a merged string
        merged_string += message + " "

        # Check for the 'EOS' (End of String) property we added to the last message
        # If we find it, exit the loop to stop receiving more messages
        if(msg.properties()['EOS']=='True'): break

    except:
        consumer.negative_acknowledge(msg)

# Print the result, except the last 'EOS' part
print(merged_string[:-4])

# Destroy the pulsar client
client.close()
