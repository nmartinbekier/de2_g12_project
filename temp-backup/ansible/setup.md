## Instructions for starting VM's and setting up Ansible 

**Starting VM's on openstack using start_instances.py**
1. Requires that the openstack RC-file is downloaded to the client machine and sourced.
2. Is key-specific - needs to be edited.
3. Needs a private and public key to be located at cluster-keys/cluster-key (and cluster-key.pub)
4. cluster-key.pub should be copied into the files consumer-cfg.txt and producer-cfg.txt
5. (~/)                        Run the command: ***source UPPMAX2022_1-1-openrc.sh***
6. (~/de2_g12_project/ansible) Run the command: ***python3 start_instances.py***
**NOTE:** If you want to automatically start ansible when running start_instances.py (with a 15 minute delay), update start_ansible=True

**Requires the packages (on client machine):**
1. nova-client
2. openstack-client
3. keystone-client
3. Ansible

**Running ansible **
1. Update /etc/ansible/hosts with the newly started machines IP-adresses
2. configuration.yml needs to be updated with correct github information
4. (~/de2_g12_project/ansible) Run the command: ***export ANSIBLE_HOST_KEY_CHECKING=False***
5. (~/de2_g12_project/ansible) Run the command: ***ansible-playbook configuration.yml --private-key=/home/ubuntu/cluster-keys/cluster-key***
