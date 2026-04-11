# SSH and SCP

Pocket deck supports SSH and SCP(SFTP).

## Authentification methods

ssh anc scp command supports password and key (RSA) authentification methods.

For password, use `-p` option.

For key authentification, put your private key to `/config/ssh/id_rsa`, and put public key to remote PC's authorized_keys file. If you search on the Internet, there are a lot of tutorials.
Pocket deck does not support key generation. The key has to to be generated on PC. For example: `ssh-keygen -t rsa -m PEM -f id_rsa`. Copy the files to Pocket deck, under /config/ssh.

## SSH

Examples:
```
ssh user@192.168.1.10

ssh user@192.168.1.10 -p password
```

## SCP

Usage: `scp local user@host:remote' or `scp user@host:remote local'. 

Examples:
```
# Remote to local
scp user@192.168.1.10:/path/to/remote /path/to/local

# Local to remote
scp /path/to/local user@192.168.1.10:/path/to/remote
```
