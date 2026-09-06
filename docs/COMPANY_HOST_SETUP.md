# Company host setup and actual release checks

This adds a runnable continuation of the existing PC-host lane. It prepares a
local Linux/WSL environment, validates real container builds and a temporary
localhost API, then can run both confirmed-free company modes and serve the
local app. It does not deploy Railway or certify answer quality from test counts.

## Windows: one launcher after prerequisites

Use a separate clean checkout of PR #79's branch, preserving existing Windows
work and stashes. Do not reset or overwrite a checkout containing other work.
Use Python 3.11+ inside a WSL 2 Linux distribution, with `python3-venv`, Git and
Docker available there. Docker Desktop's WSL integration must be enabled for
that distribution. These OS components may require local administrator action;
the launcher does not install/replace WSL, toggle privileges or enable billing.

Keep model credentials in the private environment or ignored repository `.env`.
The launcher does not copy keys from Railway, print them, or set free-eligibility
flags for you. Current free eligibility remains the existing router's prerequisite.

From PowerShell in that clean checkout:

```powershell
.\RUN_COMPANY_HOST.ps1 -Prepare -Execute -Serve -DataRoot "D:\InfinityResearchAI"
```

Optional `-Distribution Ubuntu` selects an installed WSL distribution.
Optional `-ExpectedCommit <full-reviewed-SHA>` rejects the wrong revision before
preparation. The default port is 8000; `-Port 8080` changes it.

The launcher:

1. Verifies WSL path conversion and that the selected Windows drive is mounted;
   it rejects a missing drive or drive root and never chooses a fallback drive.
2. Requires a clean committed checkout, Linux Python >=3.11, a writable data
   folder with the existing minimum free-space rule, and supported local Docker.
3. With `-Prepare`, creates `host-venv` under the selected data folder and installs
   this checkout's requirements plus pytest. It builds the reviewed execution
   image locally from the existing fixture Dockerfile using a minimal context;
   source folders, credentials and uploads are not sent as build context. No
   image is pushed. IDs are recorded in `host-runtime.json` outside the repo.
4. With `-Execute`, runs the actual Python/Node isolation/build and protected
   improvement suites. Skipped or zero-test lanes cannot pass. It starts a
   temporary app bound to a socket it owns on 127.0.0.1, runs the existing
   zero-model HTTP smoke test, and stops that server.
5. Only after host tests and eligible-free preflight pass, runs the existing live
   gate for COMPANY and COMPANY_PLUS. Each needs a fresh receipt with this exact
   revision, clean checkout and correct mode. Failure stops further live spending.
   Live research now goes through the same public AgentManager as app requests;
   company receipts also require durable runtime and worker/chief reservations.
6. With `-Serve`, starts the local app only after those checks pass in this
   invocation. It performs another localhost smoke check, prints the address and
   stays in the foreground. Ctrl+C stops the server it started.

Preparation downloads packages and images and consumes local time/disk/network;
it does not add a cloud service or a paid model fallback. Docker's own image
storage is managed by Docker Desktop, separately from DataRoot. Select its disk
location in Docker settings if the system drive must be avoided. The launcher
does not relocate an existing Docker installation or its data.

For preflight only, omit switches:

```powershell
.\RUN_COMPANY_HOST.ps1 -DataRoot "D:\InfinityResearchAI"
```

After the first setup, `-Prepare` is unnecessary. An existing Linux venv under
DataRoot is reused. The old Windows `venv` and existing launcher are preserved.
Windows path/WSL execution still requires an actual target-PC run; Linux CI does
not certify WSL, Docker Desktop integration or that PC's installation.

## Native Linux / WSL terminal

```sh
python3 scripts/run_company_host.py --data-root /absolute/private/data \
  --prepare --execute-host --check-local-api --execute-live --serve
```

For real host/API validation with no model requests:

```sh
python3 scripts/run_company_host.py --data-root /absolute/private/data \
  --execute-host --check-local-api
```

The command writes `audit/company_host_latest.json` under DataRoot. It contains
readiness, exact revision, immutable image IDs, actual suite counts, zero-model
API checks and sanitized live gate receipts. It contains no answers, source
text, private project capabilities or credentials. Missing live checks remain
NOT_TESTED; host success alone cannot make `release_ready` true.

## Current external blockers

Read-only connected Railway inspection on 2026-09-06 found the existing web
service on main with a September 4 successful deployment. Its OAuth connector
returns variable names with `valuesRedacted=true`; credential values were not
available. Railway documents that its non-privileged containers do not support
the required Docker-in-Docker workflow. Moving the web service to this branch
alone therefore cannot enable general code execution.

The attempted deployed zero-model HTTP smoke in this workspace did not run to
completion because network approval was cancelled. It is not a PASS or a failed
app-quality result. No retry through another transport, deployment or billing
change was made to circumvent that boundary.

A representative frozen research-quality campaign still needs independent
questions, grading ground truth, extraction data and available confirmed-free
models. The paired evaluator and protected software trials are implemented;
they cannot manufacture those external inputs. Existing exact-revision release
gates and deployment authority remain unchanged.

Primary setup references:

- [Docker Desktop WSL integration](https://docs.docker.com/desktop/features/wsl/)
- [Microsoft WSL commands](https://learn.microsoft.com/en-us/windows/wsl/basic-commands)
- [Railway runner limitations](https://docs.railway.com/guides/github-actions-runners#known-limitations)
- [Uvicorn socket descriptor support](https://www.uvicorn.org/settings/)
