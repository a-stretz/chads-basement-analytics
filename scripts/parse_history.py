from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from auction_engine.history import manager_profiles, parse_draft_history

raw = ROOT / "data/private/raw/draft_history.txt"
mapping = ROOT / "data/private/raw/manager_history.yaml"
out = ROOT / "data/processed/historical_transactions.csv"
profiles_out = ROOT / "data/processed/manager_profiles.csv"

df = parse_draft_history(raw, mapping)
out.parent.mkdir(parents=True, exist_ok=True)
df.to_csv(out, index=False)
manager_profiles(df).to_csv(profiles_out, index=False)
print(f"Wrote {len(df):,} transactions to {out}")
print(df.groupby("season").size().to_string())
print(f"Wrote manager profiles to {profiles_out}")
