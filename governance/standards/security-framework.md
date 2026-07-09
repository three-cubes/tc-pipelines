# Security Framework

*Comprehensive security standards, audit methodology, and incident response.*

## Security Philosophy

- **User control** — Users maintain full control over their data
- **Zero trust** — Validate all inputs, sanitise all outputs
- **Defence in depth** — Multiple layers of security controls
- **Fail securely** — System fails without exposing internals
- **Shift left** — Identify threats during design, not after implementation

---

## Core Security Standards

### Data Protection

- Only the minimum data necessary is processed and transmitted
- Sensitive data is encrypted in transit (HTTPS only) and at rest where applicable
- No user content stored or cached on external systems beyond what is required
- User behaviour is not tracked or collected without explicit consent

### Secret Management

- **Environment variables only** — API keys and secrets stored as environment variables, never in source code
- **Never logged** — Secrets never logged, printed, or stored in plain text
- **Memory protection** — Clear secrets from memory after use where possible
- **Secure input** — Use secure input methods for credential entry
- **Display protection** — Only show partial values for verification (first 10, last 4 characters)
- **Rotation** — Rotate immediately if exposed; use a secrets vault for production

### Input Validation

| Control | Standard |
|---------|----------|
| File type checking | Validate by magic number, not just extension |
| Size limits | Enforce reasonable limits to prevent resource exhaustion |
| Content sanitisation | Remove potentially dangerous patterns before processing |
| Encoding validation | Validate character encoding to prevent injection |
| Path validation | Resolve to absolute path; reject traversal attempts (`../`) |
| Character whitelist | Allow only safe characters in filenames and user inputs |

### Network Security

- All external communication over HTTPS with certificate validation
- Implement appropriate timeouts for network requests
- Respect rate limits to prevent service blocking
- Never disable SSL/TLS verification

---

## Security Response SLA

| Severity | Description | Response Time |
|----------|-------------|---------------|
| **CRITICAL** | Exploit in the wild, active data exposure | 4 hours |
| **HIGH** | Exploitable vulnerability, no proof-of-concept yet | 24 hours |
| **MEDIUM** | Requires specific conditions to exploit | 1 week |
| **LOW** | Defence in depth, minor issue | Next release |

---

## 4-Layer Defence Strategy

### Layer 1: Static Application Security Testing (SAST)

- **Trigger:** Before every commit, during development
- **Gate:** No HIGH/MEDIUM security issues; quality score meets threshold
- **Tools (language-appropriate):** Static analysers, linters, type checkers

### Layer 2: Dependency Security Analysis

- **Trigger:** Daily automated scans, before deployment
- **Gate:** No known vulnerabilities with available patches
- **Tools:** Dependency vulnerability scanners, software composition analysis

### Layer 3: Dynamic Security Testing

- **Trigger:** During test execution phase
- **Gate:** All security tests pass, no secret leakage detected
- **Approach:** Secret injection tests, error condition tests, log file analysis

### Layer 4: Source Control Security

- **Trigger:** Pre-commit hooks, periodic audits
- **Gate:** No secrets in commit history, clean commit messages
- **Tools:** Secret scanning on diffs and history

---

## Security Audit Methodology

### Phase 1: Automated Analysis (MANDATORY)

Run SAST, dependency scanning, and code quality tools. Interpret results:

- **HIGH severity** — Immediate fix required, blocks all development
- **MEDIUM severity** — Fix within current sprint, document if delayed
- **LOW severity** — Address during next refactoring cycle
- **Dependency CVEs** — Update immediately if exploit exists

### Phase 2: Manual Code Review

Focus on security-critical patterns:

- Every logging call reviewed for potential secret exposure
- All error handling checked for information disclosure
- Direct file writes reviewed for secret sanitisation
- Debug/print statements checked and removed
- Stack traces reviewed for secret exposure

### Phase 3: Dynamic Testing

- **Secret injection** — Run system with fake credentials, scan all logs
- **Error conditions** — Force errors and verify no secrets in output
- **Integration** — End-to-end workflows with secret detection
- **Log analysis** — Check all generated log files for secret patterns

### Phase 4: Validation

- Automated secret detection on codebase
- Peer review on security-critical code
- Penetration testing for high-risk changes

---

## Runtime Security Monitoring

### Log Sanitisation

All log output must pass through sanitisation that redacts patterns matching known secret formats (API keys, tokens, hashes). Sanitisation should be automatic via middleware or logging infrastructure.

### Monitoring Requirements

- System behaviour observable through metrics, logs, and traces
- Error conditions detected, logged, and reported without exposing sensitive information
- Performance baselines established and monitored for degradation
- Proactive health monitoring, not reactive

---

## Dependency Management

- **Security scanning** — Regular scans of all dependencies for known vulnerabilities
- **Version pinning** — Pin dependency versions for reproducible builds
- **Minimal dependencies** — Reduce attack surface by using the fewest dependencies needed
- **Regular updates** — Keep dependencies updated with security patches
- **Supply chain** — Verify package integrity; use trusted, well-maintained sources
- **License compliance** — Ensure all dependencies have compatible licences

---

## Incident Response

### Response Procedure

1. **Detection** — Monitoring and alerting for security-relevant events
2. **Containment** — Immediate mitigation (e.g., rotate keys, disable endpoint)
3. **Assessment** — Scope analysis: what data was potentially exposed?
4. **Remediation** — Fix root cause, not just symptoms
5. **Validation** — Enhanced security testing to confirm resolution
6. **Communication** — Notify affected parties per disclosure policy
7. **Post-incident** — Mandatory retrospective; update prevention controls

### Vulnerability Disclosure

- Responsible disclosure process for receiving and handling security reports
- Reasonable timeline for addressing reported vulnerabilities
- Clear communication about security fixes and updates

---

## Compliance Considerations

- **Data minimisation** — Process only the minimum data necessary
- **OWASP guidelines** — Follow OWASP secure coding practices and Top 10 protections
- **Regular audits** — Periodic security reviews and assessments
- **Compliance automation** — Integrate security validation into CI/CD pipelines

---

## Post-Infrastructure Security Sweep

After any session that creates cloud resources, writes config files, clones repositories, or modifies infrastructure, run a security sweep before closing the session.

### Checklist

```markdown
- [ ] Git remote URLs: no embedded credentials (PATs, tokens) in any `.git/config`
- [ ] Config files: no plaintext secrets with open permissions (expect 600 for files containing keys)
- [ ] Log files: no leaked tokens, connection strings, or API keys
- [ ] Memory/workspace files: no accidentally captured credentials from command output
- [ ] Temp directories: no clones or downloads containing embedded credentials
- [ ] Docker containers: no secrets passed as command-line arguments (use env vars or mounted files)
```

### Scan Commands

```bash
# Scan for common secret patterns in a directory
grep -rlE "(ghp_|github_pat_|sk-[a-zA-Z0-9]{20,}|Bearer [A-Za-z0-9]{20,}|InstrumentationKey=[a-f0-9-]{36})" <directory>

# Check all git repos for credentials in remote URLs
find <directory> -name ".git" -type d | while read gitdir; do
  url=$(cd "$(dirname "$gitdir")" && git remote get-url origin 2>/dev/null)
  echo "$url" | grep -qE "(ghp_|github_pat_|:[^@]+@github)" && echo "CREDENTIAL: $(dirname $gitdir)"
done

# Check file permissions on sensitive configs
find <directory> -name "*.env" -o -name "*.key" -o -name "*.pem" | xargs stat -c "%a %n" 2>/dev/null | grep -v "^600"
```

This complements the pre-commit SAST scanning (Layer 1) by covering infrastructure artefacts that don't go through the commit pipeline.

---

## Safe Config Editing

Runtime configuration files (agent config, gateway config) must be edited with surgical precision. Tools that rewrite the entire config file have caused gateway outages by corrupting JSON structure or losing fields.

### Rules

- **Never use Python `json.dump`, `sed`, or full-file overwrites** to edit JSON config files
- **Use `jq` for surgical edits:** `jq '. + {"key": "value"}' config.json > tmp && mv tmp config.json`
- **Always backup before editing:** `cp config.json config.json.bak`
- **Always validate after editing:** `jq empty config.json && echo "valid"`
- **Prefer incremental patch APIs** where available (e.g. a gateway's incremental `config.patch` API guarded by a `baseHash`)

### Safe Edit Pattern

```bash
# 1. Backup
cp config.json config.json.bak

# 2. Surgical edit with jq
jq '(.agents.list[] | select(.id == "<agent-id>") | .model.primary) = "<provider>/<new-model>"' \
  config.json > config.json.tmp

# 3. Validate
jq empty config.json.tmp || { echo "INVALID JSON — restoring"; cp config.json.bak config.json; exit 1; }

# 4. Apply
mv config.json.tmp config.json

# 5. Restart (only after validation passes)
<runtime> gateway restart
```

A purpose-built script (e.g. `safe-config-edit.sh`) handles this pattern for common agent config changes.

---

## Quick Security Commands

### Every Commit

```markdown
- [ ] No API keys in code
- [ ] No secrets in logs (sanitisation active)
- [ ] Paths validated (no traversal)
- [ ] Input sanitised (no injection)
- [ ] Errors sanitised (no info leak)
```

---

*For tactical implementation details, secure coding patterns, and checklists, use this standard and the repo standards index.*


---

## Repo adoption notes

Apply the following repo-specific rules when adopting this standard:

- Branch from current `main` and use PRs for all repo changes.
- Do not edit live runtime config directly; change templates/scripts in the repo and apply only after explicit approval.
- Do not restart the gateway or deploy live services as part of documentation or standards work.
- One complete-feature PR with evidence (diff, validation command, rollback note) — never micro-PRs; see the development-workflow standard §Branching.
