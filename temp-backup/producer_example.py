#!/usr/bin/env python3
import time
import pulsar

"""
    The implementation is used to demonstrate an intensive "conversion" function on elements
"""

# Fill in your author information
___author___ = "Nicolas Martin"
___email____ = "nicolas.martin-jimenez.5070@student.uu.se"

# Input string
INPUT_STRING = "I have a dream that my four little children will one day live in a nation where they will not be judged by the color of their skin, but by the content of their character."

def conversion(substring, operation):
    """A conversion function which takes a string as an input and outputs a converted string

    Args:
        substring (String)
        operation (function): This is an operation on the given input

    Returns:
        [String]: Converted String
    """


    # returns the conversion applied to input
    return function(substring)



def function(string):
    """ A function that performs some operation on a string. You can change the operation accordingly

    Args:
        string (String): input string on which some operation is applied

    Returns:
        [String]: string in upper case
    """
    return string.upper()


if __name__ == "__main__":

    # Create a pulsar client by supplying ip address and port
    client = pulsar.Client('pulsar://localhost:6650')

    # Create a producer on the topic that consumer can subscribe to
    producer = client.create_producer('conv-topic')

    # Use a partition_key so they go to the same partition
    partition_key = 'my_key_01'

    # Iterating on the words of the string, converting them, and sending them as a message
    for word in INPUT_STRING.split():
        producer.send((conversion(word, function)).encode('utf-8'),
            partition_key=partition_key)

    # Once we send the whole string, send a last message signalling an End of String (EOS)
    # and including a property stating EOS=True
    producer.send(("EOS").encode('utf-8'),
            partition_key=partition_key, properties=dict(EOS="True"))

    # Destroy the pulsar client
    client.close()
