from pathlib import Path
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
history = pd.read_csv(ROOT / "data/processed/historical_transactions.csv")
manager_order = sorted(history.manager.unique())
manager_map = {m: f"Manager_{i+1:02d}" for i, m in enumerate(manager_order)}
out = history.drop(columns=["fantasy_team"]).copy()
out["manager"] = out["manager"].map(manager_map)
(ROOT / "data/sample").mkdir(parents=True, exist_ok=True)
out.to_csv(ROOT / "data/sample/historical_transactions_anonymized.csv", index=False)
print(f"Wrote {len(out):,} anonymized transactions")
