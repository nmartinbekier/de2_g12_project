
"""
Source:
        Create new volume - YES
        Delete volume on Instance Delete - YES
        Image: Ubuntu 20.04 - 2021.03.23
Flavor:
        ssc.medium
Network:
        UPPMAX 2022/1-1 Internal IPv4 Network
Security Groups:
        - default: UPPMAX 2022/1-1 default security group
Key Pair
        - olzmanskeyz, update this
Configuration:
        -
Image:
        - Ubuntu 20.04 - 2021.03.23
"""

#http://docs.openstack.org/developer/python-novaclient/ref/v2/servers.html
import time, os, sys, random, re
import inspect
from os import environ as env
from  novaclient import client
import keystoneclient.v3.client as ksclient
from keystoneauth1 import loading
from keystoneauth1 import session


flavor = "ssc.medium"
private_net = "UPPMAX 2022/1-1 Internal IPv4 Network"
floating_ip_pool_name = None
floating_ip = None
image_name = "Ubuntu 20.04 - 2021.03.23"
start_ansible = True
auto_key = True

loader = loading.get_plugin_loader('password')

auth = loader.load_from_options(auth_url=env['OS_AUTH_URL'],
                                username=env['OS_USERNAME'],
                                password=env['OS_PASSWORD'],
                                project_name=env['OS_PROJECT_NAME'],
                                project_domain_id=env['OS_PROJECT_DOMAIN_ID'],
                                #project_id=env['OS_PROJECT_ID'],
                                user_domain_name=env['OS_USER_DOMAIN_NAME'])

sess = session.Session(auth=auth)
nova = client.Client('2.1', session=sess)
print ("user authorization completed.")

image = nova.glance.find_image(image_name)

flavor = nova.flavors.find(name=flavor)

if private_net != None:
    net = nova.neutron.find_network(private_net)
    nics = [{'net-id': net.id}]
else:
    sys.exit("private-net not defined.")

#print("Path at terminal when executing this file")
#print(os.getcwd() + "\n")
#---------------------------------------------------------------------worker1
cfg_file_path =  os.getcwd()+'/orchestration-config/worker-cfg.txt'
if os.path.isfile(cfg_file_path):
    userdata_worker1 = open(cfg_file_path)
else:
    sys.exit("worker-cfg.txt is not in config directory")
#---------------------------------------------------------------------worker2
cfg_file_path =  os.getcwd()+'/orchestration-config/worker-cfg.txt'
if os.path.isfile(cfg_file_path):
    userdata_worker2 = open(cfg_file_path)
else:
    sys.exit("worker-cfg.txt is not in config directory")

#---------------------------------------------------------------------worker3
cfg_file_path =  os.getcwd()+'/orchestration-config/worker-cfg.txt'
if os.path.isfile(cfg_file_path):
    userdata_worker3 = open(cfg_file_path)
else:
    sys.exit("worker-cfg.txt is not in config directory")
#---------------------------------------------------------------------worker4
cfg_file_path =  os.getcwd()+'/orchestration-config/worker-cfg.txt'
if os.path.isfile(cfg_file_path):
    userdata_worker4 = open(cfg_file_path)
else:
    sys.exit("worker-cfg.txt is not in config directory")

#---------------------------------------------------------------------client
cfg_file_path =  os.getcwd()+'/orchestration-config/client-cfg.txt'
if os.path.isfile(cfg_file_path):
    userdata_client = open(cfg_file_path)
else:
    sys.exit("client-cfg.txt is not in current working directory")

#---------------------------------------------------------------------server
cfg_file_path =  os.getcwd()+'/orchestration-config/server-cfg.txt'
if os.path.isfile(cfg_file_path):
    userdata_server = open(cfg_file_path)
else:
    sys.exit("server-cfg.txt is not in current working directory")

secgroups = ['default']

print ("Creating instances ... ")
#update key here
instance_worker1 = nova.servers.create(name="group_12_worker1", image=image, flavor=flavor, key_name='olzmanskeyz',userdata=userdata_worker1, nics=nics,security_groups=secgroups)
instance_worker2 = nova.servers.create(name="group_12_worker2", image=image, flavor=flavor, key_name='olzmanskeyz',userdata=userdata_worker2, nics=nics,security_groups=secgroups)
instance_worker3 = nova.servers.create(name="group_12_worker3", image=image, flavor=flavor, key_name='olzmanskeyz',userdata=userdata_worker3, nics=nics,security_groups=secgroups)
instance_worker4 = nova.servers.create(name="group_12_worker4", image=image, flavor=flavor, key_name='olzmanskeyz',userdata=userdata_worker4, nics=nics,security_groups=secgroups)
instance_client = nova.servers.create(name="group_12_client", image=image, flavor=flavor, key_name='olzmanskeyz',userdata=userdata_client, nics=nics,security_groups=secgroups)
instance_server = nova.servers.create(name="group_12_server", image=image, flavor=flavor, key_name='olzmanskeyz',userdata=userdata_server, nics=nics,security_groups=secgroups)

inst_status_worker1 = instance_worker1.status
inst_status_worker2 = instance_worker2.status
inst_status_worker3 = instance_worker3.status
inst_status_worker4 = instance_worker4.status
inst_status_client = instance_client.status
inst_status_server = instance_server.status


print ("waiting for 10 seconds.. ")
time.sleep(10)

while inst_status_server == 'BUILD' or inst_status_client == 'BUILD' or inst_status_worker1 == 'BUILD' or inst_status_worker2 == 'BUILD' or inst_status_worker3 == 'BUILD' or inst_status_worker4 == 'BUILD':
    print ("Instance: "+instance_worker1.name+" is in "+inst_status_worker1+" state, sleeping for 5 seconds more...")
    print ("Instance: "+instance_worker2.name+" is in "+inst_status_worker2+" state, sleeping for 5 seconds more...")
    print ("Instance: "+instance_worker3.name+" is in "+inst_status_worker3+" state, sleeping for 5 seconds more...")
    print ("Instance: "+instance_worker4.name+" is in "+inst_status_worker4+" state, sleeping for 5 seconds more...")
    print ("Instance: "+instance_client.name+" is in "+inst_status_client+" state, sleeping for 5 seconds more...")
    print ("Instance: "+instance_server.name+" is in "+inst_status_server+" state, sleeping for 5 seconds more...")
    time.sleep(5)
    os.system("clear")
    inst_status_worker1 = instance_worker1.status
    inst_status_worker2 = instance_worker2.status
    inst_status_worker3 = instance_worker3.status
    inst_status_worker4 = instance_worker4.status
    inst_status_client = instance_client.status
    inst_status_server = instance_server.status

    instance_worker1 = nova.servers.get(instance_worker1.id)
    instance_worker2 = nova.servers.get(instance_worker2.id)
    instance_worker3 = nova.servers.get(instance_worker3.id)
    instance_worker4 = nova.servers.get(instance_worker4.id)
    instance_client = nova.servers.get(instance_client.id)
    instance_server = nova.servers.get(instance_server.id)


ip_list = []

ip_address_worker1 = None
for network in instance_worker1.networks[private_net]:
    if re.match('\d+\.\d+\.\d+\.\d+', network):
        ip_address_worker1 = network
        ip_list.append(ip_address_worker1)
        break
if ip_address_worker1 is None:
    raise RuntimeError('No IP address assigned!')
#-------------------------------------------------------
ip_address_worker2 = None
for network in instance_worker2.networks[private_net]:
    if re.match('\d+\.\d+\.\d+\.\d+', network):
        ip_address_worker2 = network
        ip_list.append(ip_address_worker2)
        break
if ip_address_worker2 is None:
    raise RuntimeError('No IP address assigned!')
#-------------------------------------------------------
ip_address_worker3 = None
for network in instance_worker3.networks[private_net]:
    if re.match('\d+\.\d+\.\d+\.\d+', network):
        ip_address_worker3 = network
        ip_list.append(ip_address_worker3)
        break
if ip_address_worker3 is None:
    raise RuntimeError('No IP address assigned!')
#-------------------------------------------------------
ip_address_worker4 = None
for network in instance_worker4.networks[private_net]:
    if re.match('\d+\.\d+\.\d+\.\d+', network):
        ip_address_worker4 = network
        ip_list.append(ip_address_worker4)
        break
if ip_address_worker4 is None:
    raise RuntimeError('No IP address assigned!')
#-------------------------------------------------------

ip_address_client = None
for network in instance_client.networks[private_net]:
    if re.match('\d+\.\d+\.\d+\.\d+', network):
        ip_address_client = network
        ip_list.append(ip_address_client)
        break
if ip_address_client is None:
    raise RuntimeError('No IP address assigned!')
#-------------------------------------------------------

ip_address_server = None
for network in instance_server.networks[private_net]:
    if re.match('\d+\.\d+\.\d+\.\d+', network):
        ip_address_server = network
        ip_list.append(ip_address_server)
        break
if ip_address_server is None:
    raise RuntimeError('No IP address assigned!')


print ("Instance: "+ instance_worker1.name +" is in " + inst_status_worker1 + " state" + " ip address: "+ ip_address_worker1)
print ("Instance: "+ instance_worker2.name +" is in " + inst_status_worker2 + " state" + " ip address: "+ ip_address_worker2)
print ("Instance: "+ instance_worker3.name +" is in " + inst_status_worker3 + " state" + " ip address: "+ ip_address_worker3)
print ("Instance: "+ instance_worker4.name +" is in " + inst_status_worker4 + " state" + " ip address: "+ ip_address_worker4)
print ("Instance: "+ instance_client.name +" is in " + inst_status_client + " state" + " ip address: "+ ip_address_client)
print ("Instance: "+ instance_server.name +" is in " + inst_status_server + " state" + " ip address: "+ ip_address_server)

#update etc/ansible/hosts with IP.
text_file = open("/etc/ansible/hosts", "w")
n = text_file.write("[servers]"+"\n"+"worker1server ansible_host="+ip_address_worker1+"\n"+"worker2server ansible_host="+ip_address_worker2+"\n"+"worker3server ansible_host="+ip_address_worker3+"\n"+"worker4server ansible_host="+ip_address_worker4+"\n"+"clientserver ansible_host="+ip_address_client+"\n"+"serverserver ansible_host="+ip_address_server+"\n"+"[all:vars]" + "\n" +"ansible_python_interpreter=/usr/bin/python3" + "\n" +"[worker1server]" + "\n" +"worker1server ansible_connection=ssh ansible_user=ubuntu" + "\n" +"[worker2server]" + "\n" +"worker2server ansible_connection=ssh ansible_user=ubuntu" + "\n" +"[worker3server]" + "\n" +"worker3server ansible_connection=ssh ansible_user=ubuntu" + "\n" +"[worker4server]" + "\n" +"worker4server ansible_connection=ssh ansible_user=ubuntu" + "\n" +"[clientserver]" + "\n" +"clientserver ansible_connection=ssh ansible_user=ubuntu" + "\n" +"[serverserver]" + "\n" +"serverserver ansible_connection=ssh ansible_user=ubuntu")
text_file.close()
print("Adding worker1 ip address: " + ip_address_worker1 + " to /etc/ansible/hosts")
print("Adding worker2 ip address: " + ip_address_worker2 + " to /etc/ansible/hosts")
print("Adding worker3 ip address: " + ip_address_worker3 + " to /etc/ansible/hosts")
print("Adding worker4 ip address: " + ip_address_worker4 + " to /etc/ansible/hosts")
print("Adding client ip address: " + ip_address_client + " to /etc/ansible/hosts")
print("Adding server ip address: " + ip_address_server + " to /etc/ansible/hosts" + "\n")

#automatic adding of key to .ssh/known_hosts
if auto_key:
    os.system("bash /orchestration-config/edit_key "+str(ip_address_worker1))
    os.system("bash /orchestration-config/edit_key "+str(ip_address_worker2))
    os.system("bash /orchestration-config/edit_key "+str(ip_address_worker3))
    os.system("bash /orchestration-config/edit_key "+str(ip_address_worker4))
    os.system("bash /orchestration-config/edit_key "+str(ip_address_client))
    os.system("bash /orchestration-config/edit_key "+str(ip_address_server))

if start_ansible:
    print("Waiting for 15 minutes ...")
    time.sleep(900)
    print("Starting Ansible ...")
    os.system("export ANSIBLE_HOST_KEY_CHECKING=False")
    time.sleep(2)
    os.system("ansible-playbook configuration.yml --private-key=/home/ubuntu/cluster-keys/cluster-key")
