# Production Container Isolation Blueprint (Linux / CI)

`SubprocessPolicyAdapter` (`isolation.py`) and `IsolatedBimanualVlmPolicy` (`vlm_policy.py`) separate the untrusted athlete process using:

- Empty working directory and stripped environment variables.
- Win32 Job Object (`JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE`) on Windows or process-session kill groups (`start_new_session=True` / `os.killpg`) via `proc_sandbox.ProcessTreeGuard`.
- Allowlist-only observation serialization (`head_left`, `head_right`, `joint_pos` when tactile masking is active).

For multi-tenant public leaderboards and closed `hazard-escrowed` runs, launch the untrusted policy inside an unprivileged read-only OCI container communicating over stdio:

```bash
docker build -t habilis-athlete-sandbox -f referee/docker/Dockerfile.athlete referee/docker

docker run --rm -i \
  --network=none \
  --read-only \
  --cap-drop=ALL \
  --security-opt=no-new-privileges:true \
  --pids-limit=64 \
  --memory=2g \
  --cpus=2 \
  --tmpfs /tmp/athlete:rw,noexec,nosuid,size=256m \
  habilis-athlete-sandbox /path/to/athlete_worker.py
```

Key boundaries verified by this deployment topology:
- Zero network egress (`--network=none`).
- Zero access to referee disk targets, `seed_reveal.json`, escrow archives, or signing keys.
- Bounded memory, CPU, and fork bomb protection (`--pids-limit=64`).
