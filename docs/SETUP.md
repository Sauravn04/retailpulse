# Setup — Step 1 (Windows, VS Code)

You have Python and Git installed. Good — that is all Step 1 needs.

## 1. Check versions (in VS Code terminal, PowerShell)

```powershell
python --version
# need 3.11 or higher — if it says 3.10 or lower, install 3.11/3.12 first
git --version
```

If `python` does not work, try `py --version` — then use `py` instead
of `python` in the commands below.

## 2. Open the project

Unzip the Step 1 folder, open it in VS Code:
File → Open Folder → `retailpulse`

## 3. Virtual environment

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
# If PowerShell blocks activation, run once (as admin is not needed):
# Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
# then activate again.
```

Your prompt should now start with `(.venv)`.

## 4. Install

```powershell
pip install -r requirements.txt
pip install -r requirements-dev.txt
```

## 5. Env file

```powershell
copy .env.example .env
```

Edit `.env` only to match your local Postgres user/password.
Do not commit `.env` — it is in `.gitignore`.

## 6. Postgres (needed from Step 3, check it now if you can)

In psql, as the `postgres` superuser:

```sql
CREATE DATABASE retailpulse;
CREATE USER retailpulse_user WITH PASSWORD 'CHANGE-ME';
GRANT ALL PRIVILEGES ON DATABASE retailpulse TO retailpulse_user;
-- then, connected to retailpulse as postgres:
GRANT USAGE, CREATE ON SCHEMA public TO retailpulse_user;
```

## 7. Run the check

```powershell
python scripts/check_setup.py
```

Expected: `SETUP OK`, with Postgres `up` if it is running,
or a clear `WARN — PostgreSQL not reachable` if it is not.
Postgres down is OK in Step 1. It is not OK in Step 3.
