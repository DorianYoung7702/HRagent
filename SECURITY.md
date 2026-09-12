# Security

HRagent is a single-user Beta application. The default Compose service binds to
127.0.0.1. It does not implement user authentication or tenant isolation.
Do not expose its APIs directly to the Internet. Network deployments need an
operator-managed authentication gateway and HTTPS.

Do not post secrets or candidate information in public issues. Report security
issues through the repository's GitHub Security advisory reporting feature when
available. Otherwise ask the maintainer for a private channel without including
the vulnerability details or private data in the public request.

If a key was published, revoke and replace it. Deleting a file or making a later
commit does not remove it from Git history, forks, downloads, or caches.

See `docs/DATA_PRIVACY.md` for storage, model API calls, and deletion boundaries.
