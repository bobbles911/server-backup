#!/bin/sh
apt update
apt install -y restic
apt install python3-dotenv
snap install aws-cli --classic
#python3 backup.py install
echo "Please edit the .env file and then run './backup.py install'"