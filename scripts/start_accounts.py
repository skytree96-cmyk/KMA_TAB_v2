"""Initialize the account database before serving the production portal."""
from __future__ import annotations
import os
from pathlib import Path
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))


def main():
    if os.environ.get("TAP_POSTGRES_PREFLIGHT") == "1":
        subprocess.run([sys.executable,str(ROOT/"scripts"/"check_postgres_accounts.py"),"--render-preflight"],check=True)
    from tap.account_store import AccountStore
    store=AccountStore(os.environ.get("DATABASE_URL",""))
    store.initialize()
    bootstrap_hash=os.environ.get("BOOTSTRAP_ADMIN_PASSWORD_HASH","")
    if bootstrap_hash:
        store.bootstrap_admin(os.environ.get("BOOTSTRAP_ADMIN_LOGIN","kma.admin"),bootstrap_hash)
    if os.environ.get("TAP_SEED_SUNDAEGUK") == "1":
        from scripts.seed_sundaeguk import seed_company
        result = seed_company(store)
        import json
        print("SUNDAEGUK FIXTURE READY: " + json.dumps(result, ensure_ascii=False), flush=True)
    print("ACCOUNT DATABASE READY",flush=True)
    os.execv(sys.executable,[sys.executable,"-m","streamlit","run",str(ROOT/"streamlit_app.py"),"--server.address=0.0.0.0","--server.port="+os.environ.get("PORT","8501"),"--client.toolbarMode=minimal"])


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print("ACCOUNT STARTUP FAILED: "+type(exc).__name__,file=sys.stderr,flush=True)
        sys.exit(1)