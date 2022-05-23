"""
[servers]
prodserver ansible_host=192.168.2.31
conserver ansible_host=192.168.2.241

[all:vars]
ansible_python_interpreter=/usr/bin/python3

[prodserver]
prodserver ansible_connection=ssh ansible_user=ubuntu 
 
[devserver]
devserver ansible_connection=ssh ansible_user=ubuntu 

"""
import os

#open text file
#os.chmod("/etc/ansible/hosts", 0o755)
text_file = open("/etc/ansible/hosts", "w")
print(os.stat("/etc/ansible/hosts").st_mode)
#write string to file
n = text_file.write("FUUUUUUUUUUU[servers]" + "\n" + "prodserver ansible_host=192.168.2.31" + "\n" + "conserver ansible_host=192.168.2.241" + "\n" + "[all:vars]" + "\n" + "ansible_python_interpreter=/usr/bin/python3" + "\n" + "[prodserver]" + "\n" + "prodserver ansible_connection=ssh ansible_user=ubuntu" + "\n" + "[devserver]" + "\n" +"devserver ansible_connection=ssh ansible_user=ubsdsdsaddasdsadsadsauntu")
#close file
#text_file.close()

