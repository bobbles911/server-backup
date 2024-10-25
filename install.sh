#!/bin/bash
echo "Installing..."

INSTALL_DIR=~/.server-backup

apt update
apt install -y restic python3-dotenv pipx
pipx ensurepath
pipx install awscli

mkdir -p $INSTALL_DIR

curl -fsSL https://raw.githubusercontent.com/bobbles911/server-backup/refs/heads/main/backup.py > $INSTALL_DIR/backup.py
chmod a+x $INSTALL_DIR/backup.py

if [ ! -f $INSTALL_DIR/.env ]; then
	curl -fsSL https://raw.githubusercontent.com/bobbles911/server-backup/refs/heads/main/example.env > $INSTALL_DIR/.env
fi

echo -e "\nSuccess, but it's not running yet!"
echo -e "\nTo finished installation, please do the following:"
echo -e "- edit the configuration at '$INSTALL_DIR/.env'"
echo -e "- finish installation by running '$INSTALL_DIR/backup.py install'"
