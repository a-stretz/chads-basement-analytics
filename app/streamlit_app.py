from __future__ import annotations

from pathlib import Path
import sys

import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

st.set_page_config(page_title="Chad's Basement Analytics", layout="wide")
st.title("Chad's Basement Analytics")
st.caption("Live salary-cap draft board — market price, intrinsic bid ceiling, and remaining budget state")

board_path = ROOT / "data/processed/draft_board_2026.csv"
if not board_path.exists():
    st.warning("Generate data/processed/draft_board_2026.csv first with scripts/build_draft_board.py")
    st.stop()

board = pd.read_csv(board_path)
if "drafted" not in st.session_state:
    st.session_state.drafted = []
if "budgets" not in st.session_state:
    keeper_path = ROOT / "data/private/provisional_keepers_2026.csv"
    keeper_costs = {}
    if keeper_path.exists():
        keepers = pd.read_csv(keeper_path)
        keeper_costs = keepers.set_index("manager")["keeper_cost"].to_dict()
    st.session_state.budgets = {m: 200 - int(keeper_costs.get(m, 0)) for m in ["Stretz", "Tornabene", "Hawley", "Flappan", "Mullender", "Arnold", "Lott", "Yacos", "Eanes", "Mahoney"]}

with st.sidebar:
    st.header("Record purchase")
    remaining = board.loc[~board.player.isin([x["player"] for x in st.session_state.drafted]), "player"]
    player = st.selectbox("Player", remaining)
    manager = st.selectbox("Manager", list(st.session_state.budgets))
    price = st.number_input("Price", min_value=1, max_value=200, value=1)
    if st.button("Record sale", type="primary"):
        row = board.loc[board.player == player].iloc[0]
        if price > st.session_state.budgets[manager]:
            st.error("Price exceeds remaining budget")
        else:
            st.session_state.budgets[manager] -= int(price)
            st.session_state.drafted.append({"player": player, "manager": manager, "position": row.position, "price": int(price)})
            st.rerun()

available = board.loc[~board.player.isin([x["player"] for x in st.session_state.drafted])].copy()
cols = [c for c in ["player", "position", "projected_points", "vor", "aav", "inflated_aav", "bid_up_to", "surplus_vs_inflated_aav", "uncertainty"] if c in available.columns]
st.dataframe(available[cols], use_container_width=True, hide_index=True)

st.subheader("Remaining budgets")
st.dataframe(pd.DataFrame([{"manager": m, "budget_remaining": b} for m, b in st.session_state.budgets.items()]).sort_values("budget_remaining", ascending=False), hide_index=True, use_container_width=True)

if st.session_state.drafted:
    st.subheader("Draft log")
    st.dataframe(pd.DataFrame(st.session_state.drafted), hide_index=True, use_container_width=True)
