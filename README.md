# simple docker server backup

Backs up the following things to an S3 compatible store:

- docker databases (Postgres, MySQL, MariaDB, Redis)
- docker volumes, using restic
- any other extra file paths you specify, using restic

## Installation

`curl -fsSL https://raw.githubusercontent.com/bobbles911/server-backup/refs/heads/main/install.sh | bash`

## Example .env

```bash
# Using export you can source .env if desired
export AWS_ACCESS_KEY_ID=
export AWS_SECRET_ACCESS_KEY=
export AWS_ENDPOINT_BUCKET="s3.region.example.com/my-bucket"
# Restic encryption. Enter a password here. Try 'openssl rand -base64 30'. Don't lose it!
export RESTIC_PASSWORD=
# Email settings for notifications. Required.
export SMTP_USERNAME=
export SMTP_HOST=
export SMTP_PORT=587
export SMTP_PASSWORD=
export SYSTEM_EMAIL_NAME="My Server Robot"
export SYSTEM_EMAIL_ADDRESS="robot@example.com"
export NOTIFICATION_EMAIL_ADDRESS="your-email@example.com"
# Backup these comma separated absolute directory paths *if* they exist. Gives an error otherwise!
export EXTRA_BACKUP_PATHS=""
```
