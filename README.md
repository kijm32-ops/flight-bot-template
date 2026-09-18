# PTIS Personal Template

PTIS finds discounted Google Flights fares with SerpAPI, publishes a GitHub Pages
report, and can send the summary to your own KakaoTalk "My Chatroom". Each personal
installation uses its own GitHub repository, SerpAPI key, and Kakao Developers app.

## What stays private

`data/kakao_auth.json` contains only an encrypted Kakao refresh token. GitHub Actions
can decrypt it only with the repository's `KAKAO_TOKEN_ENCRYPTION_KEY` secret. Never
commit that encryption key, the Kakao Client Secret, a plaintext refresh token, or
other API keys. Restrict repository write access because a writer can change a
workflow that reads repository secrets.

## Recommended guided setup

### Windows

After creating your repository with **Use this template** and cloning it, open
PowerShell in the repository folder and run:

```powershell
powershell -ExecutionPolicy Bypass -File .\setup_windows.ps1
```

The bootstrap checks Python 3.11+, Git, and GitHub CLI. It repairs the current
PowerShell PATH for the standard Git and GitHub CLI install locations when those
programs are already installed. If a prerequisite is actually missing, it prints
the official `winget` command instead of silently installing software. It also runs
`gh auth login` when needed, installs `requirements.txt`, and starts the guided
installer.

### macOS / Linux / already-prepared Windows

Prerequisites:

- Python 3.11 or newer
- Git
- [GitHub CLI](https://cli.github.com/) authenticated with `gh auth login`
- a clean local clone created from the PTIS template

Run:

```bash
python -m pip install -r requirements.txt
python install_ptis.py
```

For read-only diagnostics at any time:

```bash
python install_ptis.py --doctor
```

The doctor checks Python/Git/GitHub CLI readiness, GitHub authentication, the
repository remote, working-tree state, Git commit identity presence, required
repository Secret names, encrypted Kakao auth file presence, Pages status, and the
latest Kakao verification status. It does not print secret values.

## What the guided installer does

Before asking for secrets, the installer performs a preflight check and configures
missing **repository-local** Git author settings from the authenticated GitHub
account. It uses GitHub's ID-based `noreply` commit address, so a fresh PC does not
need manual `git config user.email` setup.

A GitHub template snapshot can contain runtime history from the source instance.
For a new personal installation the installer detects meaningful history in
`data/state.json` and asks to reset it before proceeding. This gives the new user
an independent 30-day price history, exposure log, carryover state, and monthly API
budget. When deliberately reconfiguring an existing installation, run:

```bash
python install_ptis.py --preserve-state
```

After preflight, configure the Kakao Developers app with the values printed by the
installer. The fixed local Redirect URI is:

```text
http://127.0.0.1:8765/callback
```

The installer then asks through hidden prompts for:

- SerpAPI key
- Kakao REST API key
- Kakao Login Client Secret

It creates the token-encryption key itself. Secret values remain in process memory
and are never placed in command-line arguments or a plaintext config file.

The setup order is transactional:

1. perform local Kakao OAuth and verify `talk_message`;
2. if OAuth fails, retry with the same Kakao values or replace only the Kakao values
   without re-entering the SerpAPI key;
3. after OAuth succeeds, save the four required GitHub Actions secrets;
4. commit and push the new installation state and encrypted refresh token;
5. check/open GitHub Pages settings when Pages is not yet enabled;
6. optionally run **Kakao Setup Verification** and wait for the real My Chatroom
   delivery result;
7. print a final status summary containing only verified/observed states.

If setup stops before the setup commit is successfully pushed, installer-generated
changes to the state/auth files are rolled back so a retry starts from a clean
repository.

## Kakao Developers settings

Create a Kakao Developers app for the person who will receive messages, then:

1. Enable **Kakao Login**.
2. Register `http://127.0.0.1:8765/callback` as the Redirect URI.
3. Enable the `talk_message` consent item.
4. Enable the Kakao Login Client Secret for the REST API key.
5. Under Product Link Management, register the Pages web domain printed by the
   installer, normally `https://YOUR_GITHUB_OWNER.github.io`.

The OAuth browser consent must be completed while signed into the Kakao account
that should receive PTIS messages.

## Manual setup fallback

Use this only when GitHub CLI is unavailable or you prefer to configure everything
manually.

1. Enable GitHub Pages with **GitHub Actions** as its source in repository Settings.
2. Create a SerpAPI account and obtain its API key.
3. Configure the Kakao Developers app as described above.
4. Add these repository Actions secrets:

   | Secret | Required | Value |
   | --- | --- | --- |
   | `SERPAPI_KEY` | Yes | Your SerpAPI key |
   | `KAKAO_REST_API_KEY` | For Kakao | Kakao REST API key |
   | `KAKAO_CLIENT_SECRET` | For Kakao | Client Secret paired with that REST API key |
   | `KAKAO_TOKEN_ENCRYPTION_KEY` | For Kakao | Fresh Fernet key generated below |
   | `KAKAO_JS_KEY` | Optional | Kakao JavaScript key for report sharing |
   | `GMAIL_USER` / `GMAIL_PASSWORD` | Optional | Gmail address and app password |

5. Generate the encryption key:

   ```bash
   python setup_kakao.py --print-encryption-key
   ```

6. Set `KAKAO_REST_API_KEY`, `KAKAO_CLIENT_SECRET`,
   `KAKAO_TOKEN_ENCRYPTION_KEY`, and
   `KAKAO_REDIRECT_URI=http://127.0.0.1:8765/callback` in the local shell, then run:

   ```bash
   python setup_kakao.py
   ```

7. Commit only the encrypted `data/kakao_auth.json`, then run **Kakao Setup
   Verification** in Actions.

## Token rotation

The daily workflow reads and decrypts `data/kakao_auth.json`, refreshes the Kakao
access token, and persists a newly returned refresh token atomically before message
delivery. The workflow commits that encrypted file together with normal runtime
state updates when it changes.

## URLs and template behavior

On GitHub Actions, the report URL is calculated as
`https://OWNER.github.io/REPOSITORY/` from `GITHUB_REPOSITORY`. The Kakao card image
URL is also derived from the running repository and revision. `PTIS_PAGE_URL` and
`PTIS_KAKAO_CARD_IMAGE_URL` remain explicit overrides for a custom domain or local
test.

The Kakao delivery endpoint sends only to the OAuth user's own My Chatroom. PTIS
does not request the separate friend-message permission.

PTIS v1.6 can now build a verified clean distribution artifact from the upstream
source. The artifact contains only centrally managed program files plus safe seed
configuration; it excludes runtime/auth files such as `data/state.json` and
`data/kakao_auth.json`. The separate `flight-bot-template` repository still
requires a one-time repository-administration step, but its contents can be taken
directly from the **Build Clean PTIS Template** artifact.

## Clean template distribution

The upstream source repository is also a live installation, so it must not be
copied directly for new users. Build a clean distribution with:

```bash
python build_template.py --output ../ptis-template --zip ../ptis-template.zip
```

The builder uses `.ptis/update_manifest.json` as an allowlist. It includes
centrally managed program files and seed-if-missing files, while refusing protected
runtime/auth files. The generated artifact intentionally excludes:

- `data/state.json`
- `data/kakao_auth.json`
- `TASK.md`
- `CHECKPOINT.md`
- generated Pages output, caches, virtualenvs, and Git metadata

The **Build Clean PTIS Template** GitHub Actions workflow produces the same verified
zip artifact without SerpAPI calls. After the separate
`kijm32-ops/flight-bot-template` repository is created, initialize it from this
artifact and enable GitHub's template-repository setting there.

## Troubleshooting

- **Installer says the repository is dirty immediately after start:** update to the
  current template containing `.gitignore`, remove only generated cache directories
  if present, then run `python install_ptis.py --doctor`.
- **Kakao token HTTP 401:** the current setup script prints Kakao's safe
  `error`/`error_description`/`error_code` fields when available. Verify the REST
  API key and the Client Secret from the same REST key entry, and confirm the
  Client Secret is enabled.
- **Callback timeout:** the registered Redirect URI must exactly match
  `http://127.0.0.1:8765/callback`, and local port 8765 must be available.
- **Git commit identity:** guided setup configures this automatically only inside
  the current repository. `--doctor` reports whether an identity is available.
- **No Kakao card image:** the image URL must be publicly reachable by Kakao.
- **Setup interrupted before commit:** rerun the installer. It rolls back the local
  runtime/auth changes it generated before a successful setup commit.

## Focus Search

Focus Search adds one explicit user-intent search without increasing the normal
monthly SerpAPI budget. When enabled, it replaces the lowest-priority daily
`GMP/near` discovery task one-for-one. When disabled or expired, the original
`GMP/near` task runs normally.

Edit `user_config.json`:

```json
{
  "focus_search": {
    "enabled": true,
    "origin": "ICN",
    "region": "Japan",
    "outbound_from": "2026-10-02",
    "outbound_to": "2026-10-11",
    "stay_min": 3,
    "stay_max": 5,
    "max_price": 250000
  }
}
```

Required when enabled: `origin`, `region`, `outbound_from`, and
`outbound_to`. `stay_min` and `stay_max` are optional but must be supplied
together. `max_price` is optional.

The current Google Flights Deals API does not allow `query` and `trip_length`
in the same request. PTIS therefore expresses a requested stay such as 3-5 days
inside the region query while keeping the explicit outbound-date window. Focus
results still pass PTIS normalization and price-safety gates, but they do not
compete with discovery quota, carryover, or exposure demotion. They appear first
in Kakao and in a separate Pages section.

If the entire focus date window has passed, Focus Search is skipped automatically
and the normal `GMP/near` discovery slot is restored. Invalid Focus settings also
disable only Focus for that run; the discovery pipeline continues.

## Exact Route Watch

Route Watch monitors one exact airport pair and exact round-trip dates with the
SerpAPI `google_flights` engine. It shares the same one-per-day user-intent slot
used by Region Focus, so it does not add a new scheduled API call.

Example `user_config.json`:

```json
{
  "focus_slot": {
    "mode": "alternate"
  },
  "focus_search": {
    "enabled": true,
    "origin": "ICN",
    "region": "Japan",
    "outbound_from": "2026-10-02",
    "outbound_to": "2026-10-11",
    "stay_min": 3,
    "stay_max": 5,
    "max_price": 250000
  },
  "route_watch": {
    "enabled": true,
    "origin": "ICN",
    "destination": "NRT",
    "outbound_date": "2026-10-03",
    "return_date": "2026-10-06",
    "max_price": 300000,
    "nonstop_only": true
  }
}
```

`focus_slot.mode` controls which user-intent search gets the single daily slot
when both are active:

- `alternate` (default): alternate Region Focus and Route Watch by KST date;
- `route_first`: always prefer Route Watch while it is active;
- `region_first`: always prefer Region Focus while it is active.

If only one feature is active, that feature gets the slot. If neither is active,
the original `GMP/near` discovery task is restored.

The initial `google_flights` response includes the round-trip fare for each
outbound option. v1.4 intentionally does not send the optional
`departure_token` follow-up request because PTIS only needs the monitored
round-trip price at this stage. Return-flight choice details and booking-token
lookups are outside v1.4.

Route Watch results do not compete with Discovery carryover, quota, or exposure
demotion. They are displayed before Region Focus and Discovery in Kakao and on the
Pages report. An invalid or expired Route Watch disables only that watch for the
current run.

## Schedule and API budget

The normal workflow still runs every day at UTC 22:00 (KST 07:00). Region Focus
and Exact Route Watch share one replacement slot rather than adding calls, so the
normal schedule remains about **221 calls/month** (7 daily tasks plus the weekly
deep task) against the 235-call safety budget. v1.4 adds **0 net scheduled SerpAPI
calls**.

## Updating an installed PTIS repository

PTIS v1.5 adds a protected update path for repositories that were already created
from PTIS. Program files can follow the upstream project while personal state stays
inside the installed repository.

The update source of truth is:

- upstream: `kijm32-ops/flight-bot`
- branch: `main`
- version: `PTIS_VERSION`
- file policy: `.ptis/update_manifest.json`

The manifest separates centrally managed program files from personal files.
Updates never overwrite an existing:

- `data/state.json`
- `data/kakao_auth.json`
- `user_config.json`

Repository Secrets are not Git files and are not changed by the updater. A legacy
install that does not yet have `user_config.json` receives the current disabled
default once; after that, the file is user-owned.

### Check or apply locally

Read-only check:

```bash
python update_ptis.py --check
```

Apply the latest managed files to a clean working tree:

```bash
python update_ptis.py --apply
```

The updater fetches upstream once, pins the exact fetched commit, validates the
manifest, and applies only managed files from that snapshot. It refuses a dirty
working tree before changing files. Review `git diff --cached` before committing.

### Update pull requests

Installed repositories that already contain v1.5 run **PTIS Update Check** weekly
and can also run it manually from Actions. When a newer PTIS version exists, the
workflow creates an update branch and attempts to open a pull request. Nothing is
merged automatically.

GitHub may require the repository setting that allows GitHub Actions to create
pull requests. If that permission is disabled, the workflow still pushes the
update branch and prints a warning so the owner can open the PR manually.

Repositories installed before v1.5 need a one-time bootstrap update to receive
`update_ptis.py`, the manifest, version file, and update workflow. After that,
normal updates use the same mechanism.

## Development validation

```bash
python -m py_compile *.py
python -m unittest
```

Pull requests also run **Validate PTIS**, which compiles Python, runs unit tests,
parses workflow YAML, and checks diff whitespace without calling SerpAPI.
