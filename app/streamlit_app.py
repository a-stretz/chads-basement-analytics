from __future__ import annotations

import json
from pathlib import Path
import sys

import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from auction_engine.draft_state import DraftValidationError
from auction_engine.draft_ui import (
    draft_input_version,
    get_or_load_draft_resources,
    nomination_labels,
    prepare_nomination_pool,
)
from auction_engine.ledger import LedgerError
from auction_engine.live_draft import (
    LiveDraftSession,
    RecalculationError,
    load_draft_inputs,
)


st.set_page_config(page_title="Chad's Basement Analytics", layout="wide")
st.title("Chad's Basement Analytics")
st.caption(
    "Live salary-cap draft board — replayed budgets, active-lineup value, "
    "and opportunity-cost Bid-Up-To"
)

config_path = ROOT / "config/cbxii.yaml"
pool_path = ROOT / "data/processed/draft_pool_2026.csv"
context_path = ROOT / "data/processed/draft_context_2026.json"
keepers_path = ROOT / "data/private/provisional_keepers_2026.csv"
required_paths = (config_path, pool_path, context_path, keepers_path)
missing_paths = [path for path in required_paths if not path.exists()]
if missing_paths:
    st.warning(
        "Missing live draft input(s): "
        + ", ".join(str(path.relative_to(ROOT)) for path in missing_paths)
        + ". Generate artifacts with scripts/build_draft_board.py first."
    )
    st.stop()


def load_live_resources():
    loaded_inputs = load_draft_inputs(
        config_path=config_path,
        pool_path=pool_path,
        context_path=context_path,
        keepers_path=keepers_path,
    )
    loaded_context = json.loads(context_path.read_text(encoding="utf-8"))
    loaded_ledger_path = ROOT / "state" / "draft_2026.json"
    loaded_session = (
        LiveDraftSession.load(loaded_ledger_path, loaded_inputs)
        if loaded_ledger_path.exists()
        else LiveDraftSession.create(
            loaded_ledger_path,
            loaded_inputs,
            loaded_context["draft_id"],
        )
    )
    return loaded_inputs, loaded_context, loaded_session


try:
    input_version = draft_input_version(required_paths)
    inputs, context, session = get_or_load_draft_resources(
        st.session_state,
        input_version,
        load_live_resources,
    )
except (DraftValidationError, LedgerError, RecalculationError, OSError, ValueError) as error:
    st.error(f"Could not initialize the live draft: {error}")
    st.stop()

result = session.snapshot()
active_sales = tuple(result.state.active_sales)
modeled_available = prepare_nomination_pool(
    result.available,
    inputs.rules.modeled_positions,
)
player_labels = nomination_labels(modeled_available)

with st.sidebar:
    st.header("Current nomination / sale")
    keeper_summary = " · ".join(
        f"{status}: {count}" for status, count in inputs.keeper_status_counts if count
    )
    if keeper_summary:
        st.caption(f"Keeper file — {keeper_summary}")
    player_key = st.selectbox(
        "Player",
        options=modeled_available.player_key.tolist(),
        format_func=lambda key: player_labels[key],
        index=None,
        placeholder="Search available players",
    )
    entry_columns = st.columns([2, 1])
    manager_name = entry_columns[0].selectbox(
        "Winning manager",
        options=inputs.rules.managers,
    )
    manager_state = result.state.managers[manager_name]
    legal_sale = (
        player_key is not None
        and manager_state.roster_slots_remaining > 0
        and manager_state.maximum_legal_bid >= inputs.rules.min_bid
    )
    price_max = max(inputs.rules.min_bid, manager_state.maximum_legal_bid)
    price = entry_columns[1].number_input(
        "Winning bid",
        min_value=inputs.rules.min_bid,
        max_value=price_max,
        value=inputs.rules.min_bid,
        step=1,
        disabled=not legal_sale,
    )
    if player_key is not None:
        nomination = result.board.loc[
            result.board.player_key.eq(player_key)
        ].iloc[0]
        bid_up_to = (
            "—"
            if pd.isna(nomination.bid_up_to)
            else f"${int(nomination.bid_up_to)}"
        )
        market_estimate = (
            "—"
            if pd.isna(nomination.inflated_aav)
            else f"${int(round(float(nomination.inflated_aav)))}"
        )
        nomination_metrics = st.columns(3)
        nomination_metrics[0].metric(
            "League AAV",
            f"${int(round(float(nomination.normalized_aav)))}",
        )
        nomination_metrics[1].metric("Market est.", market_estimate)
        nomination_metrics[2].metric("Bid-Up-To", bid_up_to)
        position_need = manager_state.starter_needs.get(
            str(nomination.position),
            0,
        )
        flex_need = (
            manager_state.flex_need
            if nomination.position in inputs.rules.flex_eligible
            else 0
        )
        st.caption(
            f"{nomination.position} · {float(nomination.projected_points):.1f} projected pts · "
            f"starter need {position_need}"
            + (f" · FLEX need {flex_need}" if nomination.position in inputs.rules.flex_eligible else "")
        )
    st.caption(
        f"{manager_name}: ${manager_state.budget_remaining} left · "
        f"{manager_state.roster_slots_remaining} slots · "
        f"max legal bid ${manager_state.maximum_legal_bid}"
    )
    if st.button(
        "Record sale",
        type="primary",
        use_container_width=True,
        disabled=not legal_sale,
    ):
        try:
            session.record_sale(str(player_key), manager_name, int(price))
            st.rerun()
        except (DraftValidationError, LedgerError, RecalculationError, OSError) as error:
            st.error(str(error))

    unmodeled_positions = [
        position
        for position, maximum in sorted(inputs.rules.position_max.items())
        if position not in inputs.rules.modeled_positions and int(maximum) > 0
    ]
    with st.expander("Record DST/K purchase"):
        if not unmodeled_positions:
            st.caption("No required unmodeled positions are enabled.")
        else:
            manual_player = st.text_input(
                "Player / unit name",
                key="unmodeled-player",
            )
            manual_position = st.selectbox(
                "Position",
                options=unmodeled_positions,
                key="unmodeled-position",
            )
            manual_manager = st.selectbox(
                "Winning manager",
                options=inputs.rules.managers,
                key="unmodeled-manager",
            )
            manual_state = result.state.managers[manual_manager]
            manual_legal = (
                bool(manual_player.strip())
                and manual_state.roster_slots_remaining > 0
                and manual_state.position_capacity.get(manual_position, 0) > 0
                and manual_state.maximum_legal_bid >= inputs.rules.min_bid
            )
            manual_price = st.number_input(
                "Winning bid",
                min_value=inputs.rules.min_bid,
                max_value=max(
                    inputs.rules.min_bid,
                    manual_state.maximum_legal_bid,
                ),
                value=inputs.rules.min_bid,
                step=1,
                disabled=not manual_legal,
                key="unmodeled-price",
            )
            st.caption(
                f"{manual_manager}: ${manual_state.budget_remaining} left · "
                f"{manual_state.roster_slots_remaining} slots · "
                f"max legal bid ${manual_state.maximum_legal_bid}"
            )
            if st.button(
                "Record DST/K sale",
                use_container_width=True,
                disabled=not manual_legal,
            ):
                try:
                    session.record_unmodeled_sale(
                        player=manual_player,
                        position=manual_position,
                        manager=manual_manager,
                        price=int(manual_price),
                    )
                    st.rerun()
                except (
                    DraftValidationError,
                    LedgerError,
                    RecalculationError,
                    OSError,
                ) as error:
                    st.error(str(error))

    st.divider()
    if active_sales:
        last_sale = max(active_sales, key=lambda sale: sale.order)
        if st.button(
            f"Undo last: {last_sale.player} (${last_sale.price})",
            use_container_width=True,
        ):
            try:
                session.undo_sale(last_sale.sale_id)
                st.rerun()
            except (DraftValidationError, LedgerError, RecalculationError, OSError) as error:
                st.error(str(error))
    else:
        st.caption("No sales to undo.")

    with st.expander("Edit an earlier sale"):
        if not active_sales:
            st.caption("No active sales.")
        else:
            sales_by_id = {sale.sale_id: sale for sale in active_sales}
            edit_id = st.selectbox(
                "Sale",
                options=[sale.sale_id for sale in reversed(active_sales)],
                format_func=lambda sale_id: (
                    f"#{sales_by_id[sale_id].order} "
                    f"{sales_by_id[sale_id].player} — "
                    f"{sales_by_id[sale_id].manager} ${sales_by_id[sale_id].price}"
                ),
            )
            current = sales_by_id[edit_id]
            editable_keys = [
                current.player_key,
                *modeled_available.player_key.tolist(),
            ]
            all_labels = {
                row.player_key: f"{row.player} — {row.position}"
                for row in inputs.players.itertuples()
            }
            for sale in active_sales:
                all_labels.setdefault(
                    sale.player_key,
                    f"{sale.player} — {sale.position}",
                )
            with st.form("edit-sale"):
                corrected_key = st.selectbox(
                    "Correct player",
                    options=editable_keys,
                    format_func=lambda key: all_labels[key],
                )
                corrected_manager = st.selectbox(
                    "Correct manager",
                    options=inputs.rules.managers,
                    index=inputs.rules.managers.index(current.manager),
                )
                corrected_price = st.number_input(
                    "Correct price",
                    min_value=inputs.rules.min_bid,
                    max_value=inputs.rules.salary_cap,
                    value=current.price,
                    step=1,
                )
                save_edit = st.form_submit_button(
                    "Save correction",
                    use_container_width=True,
                )
            if save_edit:
                try:
                    projection_keys = set(inputs.players.player_key)
                    edited_player_key = (
                        None
                        if current.player_key not in projection_keys
                        and corrected_key == current.player_key
                        else corrected_key
                    )
                    session.edit_sale(
                        edit_id,
                        player_key=edited_player_key,
                        manager=corrected_manager,
                        price=int(corrected_price),
                    )
                    st.rerun()
                except (
                    DraftValidationError,
                    LedgerError,
                    RecalculationError,
                    OSError,
                ) as error:
                    st.error(str(error))

target = result.state.managers[inputs.target_manager]
metric_columns = st.columns(4)
metric_columns[0].metric("Target budget", f"${target.budget_remaining}")
metric_columns[1].metric("Target slots", target.roster_slots_remaining)
metric_columns[2].metric("Target max bid", f"${target.maximum_legal_bid}")
metric_columns[3].metric("League market", f"{result.market_inflation:.2f}×")

st.subheader("Live recommendations")
board_columns = [
    column
    for column in (
        "player",
        "position",
        "projected_points",
        "vor",
        "inflated_aav",
        "bid_up_to",
        "aav",
        "uncertainty",
    )
    if column in result.board.columns
]
st.dataframe(
    result.board[board_columns],
    use_container_width=True,
    hide_index=True,
    height=520,
)

st.subheader("Manager state")
manager_rows = []
for name in inputs.rules.managers:
    manager = result.state.managers[name]
    needs = {**manager.starter_needs, "FLEX": manager.flex_need}
    manager_rows.append(
        {
            "manager": name,
            "budget_remaining": manager.budget_remaining,
            "roster_slots_remaining": manager.roster_slots_remaining,
            "maximum_legal_bid": manager.maximum_legal_bid,
            "roster": ", ".join(entry.player for entry in manager.roster),
            "starter_needs": ", ".join(
                f"{position}:{count}"
                for position, count in sorted(needs.items())
                if count
            )
            or "complete",
        }
    )
st.dataframe(pd.DataFrame(manager_rows), hide_index=True, use_container_width=True)

if active_sales:
    st.subheader("Active draft ledger")
    st.dataframe(
        pd.DataFrame(
            [
                {
                    "order": sale.order,
                    "player": sale.player,
                    "position": sale.position,
                    "manager": sale.manager,
                    "price": sale.price,
                    "sale_id": sale.sale_id,
                }
                for sale in active_sales
            ]
        ),
        hide_index=True,
        use_container_width=True,
    )

