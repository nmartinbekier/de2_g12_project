## Instructions for starting VM's and setting up Ansible 

** Starting VM's on openstack using start_instances.py **
1. Requires that the openstack RC-file is downloaded to the client machine and sourced.
2. Is key-specific - needs to be edited.
3. Needs a private and public key to be located at cluster-keys/cluster-key (and cluster-key.pub)
4. cluster-key.pub should be copied into the files consumer-cfg.txt and producer-cfg.txt
5. Run the command: ** python3 start_instances.py **

** Requires the packages (on client machine): **
1. nova-client
2. openstack-client
3. keystone-client
3. Ansible

** Running ansible **
1. Update /etc/ansible/hosts with the newly started machines IP-adresses
2. configuration.yml needs to be updated with correct github information
3. run the command: ** ansible-playbook configuration.yml --private-key=/home/ubuntu/cluster-keys/cluster-key **
