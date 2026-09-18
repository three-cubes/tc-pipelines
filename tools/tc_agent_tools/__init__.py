"""Trusted off-CI host-broker tooling for Three Cubes repos.

Currently exposes `agent-token` — mint a short-lived per-agent GitHub App
installation token from Key Vault. It is the lower-level broker complement to
the CI `github-app-token` composite action, not a direct agent-harness interface.
"""
