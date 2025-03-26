#!/usr/bin/env python3
import subprocess, os, re, sys, smtplib
from datetime import datetime, timedelta
from email.mime.text import MIMEText
from dotenv import load_dotenv

def send_email(sender_email, recipient_email, subject, message, sender_name=None, recipient_name=None):
	msg = MIMEText(message)

	if sender_name:
		msg["From"] = f"{sender_name} <{sender_email}>"
	else:
		msg["From"] = sender_email

	if recipient_name:
		msg["To"] = f"{recipient_name} <{recipient_email}>"
	else:
		msg["To"] = recipient_email
	
	msg["Subject"] = subject

	server = smtplib.SMTP(os.environ["SMTP_HOST"], int(os.environ.get("SMTP_PORT", 587)))
	server.starttls()
	server.login(os.environ["SMTP_USERNAME"], os.environ["SMTP_PASSWORD"])
	server.sendmail(sender_email, recipient_email, msg.as_string())

def send_report(message, success=False):
	print(message)

	if os.environ.get("SMTP_PASSWORD", None):
		hostname = run_command("hostname")

		# Assuming the script is run around midnight, then 6 hours ago should be the previous day.
		backup_day = (datetime.now() - timedelta(hours=6)).strftime("%a %d")

		send_email(
			os.environ["SYSTEM_EMAIL_ADDRESS"],
			os.environ["NOTIFICATION_EMAIL_ADDRESS"],
			(f"{backup_day} - Backup of {hostname} was successful ^_^" if success else
				f"Warning: {backup_day.upper()} {hostname} BACKUP FAILED *_*"),
			message,
			sender_name=os.environ["SYSTEM_EMAIL_NAME"]
		)

def run_command(command):
	result = subprocess.run(command, shell=True, text=True, capture_output=True, check=True)
	#print(result.stdout.strip())
	return result.stdout.strip()

def run_command_nocheck(command):
	try:
		result = subprocess.run(command, shell=True, text=True, capture_output=True, check=True)
		return result.stdout.strip()
	except subprocess.CalledProcessError:
		return None

def get_server_name():
	return run_command("hostname") + "-" + run_command("cat /etc/machine-id")

def get_restic_repo(aws_endpoint_bucket, server_name):
	return f"s3:{aws_endpoint_bucket}/restic/{server_name}"

def get_db_bucket_path(s3_bucket, server_name):
	return f"{s3_bucket}/databases/{server_name}"

def binary_exists_in_container(container_id, binary_name):
	return run_command_nocheck(f"docker exec {container_id} sh -c 'command -v \"{binary_name}\"'") is not None

class PostgresProvider:
	def get_db_name(self, env_vars):
		return env_vars.get("POSTGRES_DB", "postgres")

	def backup(self, container_id, env_vars, backup_path):
		db_name = self.get_db_name(env_vars)
		user = env_vars.get("POSTGRES_USER", "postgres")

		# postgres wants the password in an env var
		os.environ["PGPASSWORD"] = env_vars.get("POSTGRES_PASSWORD", "")

		run_command(f"docker exec {container_id} pg_dump -U {user} -d {db_name} > {backup_path}")

class MysqlMariaDBProvider:
	def get_db_name(self, env_vars):
		return env_vars.get("MARIADB_DATABASE") or env_vars.get("MYSQL_DATABASE", "")

	def backup(self, container_id, env_vars, backup_path):
		db_name = self.get_db_name(env_vars)
		user = env_vars.get("MARIADB_USER") or env_vars.get("MYSQL_USER", "root")
		password = env_vars.get("MARIADB_PASSWORD") or env_vars.get("MYSQL_PASSWORD", "")
		dump_binary = "mariadb-dump" if binary_exists_in_container(container_id, "mariadb-dump") else "mysqldump"

		run_command(f"docker exec {container_id} {dump_binary} -u {user} -p{password} {db_name} > {backup_path}")

class RedisProvider:
	def get_db_name(self, env_vars):
		return "redis"

	def backup(self, container_id, env_vars, backup_path):
		run_command(f"docker exec {container_id} redis-cli save")
		# Copy the dump file from the container to the backup directory
		run_command(f"docker cp {container_id}:/data/dump.rdb {backup_path}")

def get_backup_definition(container_id, image, name):
	BACKUP_DEFINITIONS = [
		(["mariadb"], "mysqld", MysqlMariaDBProvider(), "mariadb.sql"),
		(["mysql"], "mysqld", MysqlMariaDBProvider(), "mysql.sql"),
		(["postgres"], "postgres", PostgresProvider(), "postgres.sql"),
		(["redis"], "redis-server", RedisProvider(), "rdb")
	]

	for backup_definition in BACKUP_DEFINITIONS:
		patterns = backup_definition[0]
		process_name = backup_definition[1]

		pattern_matches = any(pattern in image.lower() or pattern in name.lower() for pattern in patterns)
		process_matched = process_name in get_main_process(container_id)

		# Must match by container image/name and also contain a correct process
		if pattern_matches and process_matched:
			return backup_definition
	
	return None

# Get docker containers
def get_containers():
	output = run_command("docker ps --format '{{.ID}} {{.Image}} {{.Names}}'")
	# container_id, image, name for each
	return [line.split(maxsplit=2) for line in output.splitlines()]

# Get commandline used to launch main process
def get_main_process(container_id):
	return run_command(f"docker exec {container_id} cat /proc/1/cmdline")

# Get environment variables from a container
def get_env_vars(container_id):
	env_output = run_command(f"docker exec {container_id} env")
	# Get the env and also remove any empty vars
	env_vars = {
		key : value for key, value in (
			line.split("=", 1) for line in env_output.splitlines() if "=" in line
		) if value
	}
	return env_vars

# Main backup function
def backup_databases(backup_dir, s3_endpoint, db_bucket_path):
	success = True
	timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

	backup_names = [] # for informational purposes
	containers = get_containers()

	if not containers:
		print("No containers found.")
		return

	for container_info in containers:
		container_id, image, name = container_info
		backup_definition = get_backup_definition(container_id, image, name)

		if backup_definition:
			_, _, backup_provider, ext = backup_definition
			env_vars = get_env_vars(container_id)
			db_name = backup_provider.get_db_name(env_vars)

			backup_name = f"{container_id}_{name}_{db_name}_{timestamp}.{ext}"
			backup_names.append(backup_name)

			backup_path = os.path.join(backup_dir, backup_name)

			try:
				print(f"Backing up {name} ({image}) to {backup_path}")
				backup_provider.backup(container_id, env_vars, backup_path)

				# Need to upload to S3 here!
				run_command(f"aws s3 cp '{backup_path}' 's3://{db_bucket_path}/{backup_name}' --endpoint-url='https://{s3_endpoint}'")
				os.remove(backup_path)
			except Exception as e:
				send_report(f"A database backup failed: {backup_name}\n{e}")
				success = False

	print(f"Database backups complete.")
	return (success, backup_names)

# Backup docker volumes plus any extra given paths using restic.
def backup_volumes():
	success = True
	backup_paths = ["/var/lib/docker/volumes"]

	extra_backup_paths = os.environ.get("EXTRA_BACKUP_PATHS", None)

	if extra_backup_paths:
		backup_paths.extend(extra_backup_paths.split(","))

	run_command("restic unlock")

	for backup_path in backup_paths:
		if os.path.exists(backup_path):
			print("Backing up", backup_path)

			try:
				run_command(f"restic backup --verbose --exclude-caches '{backup_path}'")
			except Exception as e:
				send_report(f"Volume backup failed: {backup_path}\n{e}")
				success = False
		else:
			send_report(f"Backup path did not exist: {backup_path}")
			success = False
	
	run_command("restic forget --verbose --keep-daily 30 --keep-weekly 52 --prune")
	run_command("restic check")
	
	return (success, backup_paths)

def main():
	try:
		abs_script_path = os.path.realpath(__file__)
		abs_script_dir = os.path.dirname(abs_script_path)
		abs_db_dump_dir = os.path.join(abs_script_dir, "db-dump-temp")
		abs_dotenv_path = os.path.join(abs_script_dir, ".env")

		load_dotenv(abs_dotenv_path)
		aws_endpoint_bucket = os.environ["AWS_ENDPOINT_BUCKET"]

		os.makedirs(abs_db_dump_dir, exist_ok=True)

		server_name = get_server_name()
		s3_endpoint, s3_bucket = aws_endpoint_bucket.split(sep="/", maxsplit=1)

		restic_repo = get_restic_repo(aws_endpoint_bucket, server_name)
		db_bucket_path = get_db_bucket_path(s3_bucket, server_name)

		os.environ["RESTIC_REPOSITORY"] = restic_repo

		if len(sys.argv) > 1 and sys.argv[1] == "install":
			print("Installing...")
			print("Initialising restic repository...")

			try:
				run_command("restic cat config")
			except subprocess.CalledProcessError as e:
				print("Restic repo not detected, initialising now...")
				run_command("restic init")
			else:
				print("Restic repo already exists.")

			print("Creating cron.daily...")
			run_command(f"ln -sf '{abs_script_path}' /etc/cron.daily/server-backup")
			print("Done")
		elif len(sys.argv) > 1 and sys.argv[1] == "uninstall":
			print("Removing cron.daily...")
			os.remove("/etc/cron.daily/server-backup")
			print(f"Done. You'll need to manually delete the directory {abs_script_dir}")
		else:
			print("Backing up... " + server_name)
			print(" s3 endpoint", s3_endpoint)
			print(" s3 bucket", s3_bucket)
			print(" restic repo " + restic_repo)
			print(" db bucket path " + db_bucket_path)

			print("Backing up databases...")
			db_backup_success, db_names = backup_databases(abs_db_dump_dir, s3_endpoint, db_bucket_path)

			print("Backing up volumes...")
			vol_backup_success, vol_paths = backup_volumes()

			if db_backup_success and vol_backup_success:
				send_report(
					"All backups were successful.\n"
					+ "\n"
					+ f"Server name: {server_name}\n"
					+ f"S3 Endpoint: {s3_endpoint}\n"
					+ f"S3 Bucket: {s3_bucket}\n"
					+ f"Database backup path: {db_bucket_path}\n"
					+ f"Restic repository: {restic_repo}\n"
					+ "\n"
					+ "Databases backed up:\n"
					+ "".join([f" {name}\n" for name in db_names])
					+ "\n"
					+ "Paths backed up with restic:\n"
					+ "".join([f" {path}\n" for path in vol_paths])
					+ "\n"
					+ "Restic repository commands:\n"
					+ f" restic -r {restic_repo} mount /mnt/restic\n"
					+ f" restic -r {restic_repo} snapshots\n"
				, True)
			else:
				print("Something failed.")

	except Exception as e:
		send_report(f"Unhandled exception:\n{e}")
		raise e

main()
