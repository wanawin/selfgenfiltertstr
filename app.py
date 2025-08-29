# app.py
import streamlit as st
from itertools import permutations, combinations_with_replacement
import csv
import os
from collections import Counter

# =========================
# Static mappings (unchanged)
# =========================
V_TRAC_GROUPS = {0:1,5:1,1:2,6:2,2:3,7:3,3:4,8:4,4:5,9:5}
MIRROR_PAIRS = {0:5,5:0,1:6,6:1,2:7,7:2,3:8,8:3,4:9,9:4}
MIRROR = MIRROR_PAIRS

def sum_category(total: int) -> str:
    if 0 <= total <= 15:
        return 'Very Low'
    elif 16 <= total <= 24:
        return 'Low'
    elif 25 <= total <= 33:
        return 'Mid'
    else:
        return 'High'

# =========================
# Load filters (unchanged)
# =========================
def load_filters(path: str='lottery_filters_batch10.csv') -> list:
    if not os.path.exists(path):
        st.error(f"Filter file not found: {path}")
        st.stop()
    filters = []
    with open(path, newline='', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for raw in reader:
            row = {k.lower(): v for k, v in raw.items()}
            row['id'] = row.get('id', row.get('fid', '')).strip()
            for key in ('name', 'applicable_if', 'expression'):
                if key in row and isinstance(row[key], str):
                    row[key] = row[key].strip().strip('"').strip("'")
            row['expression'] = row.get('expression', '').replace('!==', '!=')
            applicable = row.get('applicable_if') or 'True'
            expr = row.get('expression') or 'False'
            try:
                row['applicable_code'] = compile(applicable, '<applicable>', 'eval')
                row['expr_code'] = compile(expr, '<expr>', 'eval')
            except SyntaxError as e:
                st.error(f"Syntax error in filter {row['id']}: {e}")
                continue
            row['enabled_default'] = row.get('enabled', '').lower() == 'true'
            filters.append(row)
    return filters

# =========================
# Pair parsing & generation (only change to generation)
# =========================
def _clean_pairs(raw: str):
    """Parse comma-separated 'pairs' like '01, 27,56' → ['01','27','56'] (2 numeric chars)."""
    items = [p.strip() for p in (raw or "").split(",") if p.strip() != ""]
    return [p for p in items if len(p) == 2 and p.isdigit()]

def _unique_permutations(s: str):
    """Yield ALL unique permutations (straights) of a 5-char string, honoring repeats."""
    seen = set()
    for tup in permutations(s, 5):
        cand = ''.join(tup)
        if cand not in seen:
            seen.add(cand)
            yield cand

def generate_permutation_pool(seed: str, group_a: list[str], group_b: list[str]) -> list[str]:
    """
    New generator:
      For each seed digit, for each pair in A×B:
        base = sd + pairA + pairB  (length 5)
        emit ALL unique permutations (straights) of base
    """
    pool = set()
    for sd in seed:
        if not sd.isdigit():
            continue
        for a in group_a:
            for b in group_b:
                base = sd + a + b
                if len(base) == 5 and base.isdigit():
                    for perm in _unique_permutations(base):
                        pool.add(perm)
    return sorted(pool)

# =========================
# Primary Percentile Filter (sum-based; uses DEFAULTS ONLY)
# =========================
def _parse_percentile_zones(zones_str: str):
    """
    Parse '0–26, 30–35, 36–43' (supports '-' or '–') → [(0,26),(30,35),(36,43)].
    """
    if not zones_str or not zones_str.strip():
        return []
    norm = zones_str.replace('–', '-')
    out = []
    for piece in norm.split(','):
        r = piece.strip()
        if not r:
            continue
        if '-' in r:
            a, b = r.split('-', 1)
            try:
                lo, hi = int(a.strip()), int(b.strip())
                if lo <= hi:
                    out.append((lo, hi))
            except:
                pass
    return out

def _percentile_ranks(values):
    """Percentile rank (0..100) per value with average ranks for ties."""
    n = len(values)
    if n == 0:
        return []
    idx = list(range(n))
    idx.sort(key=lambda i: values[i])
    ranks = [0.0]*n
    i = 0
    while i < n:
        j = i
        while j+1 < n and values[idx[j+1]] == values[idx[i]]:
            j += 1
        avg_rank = (i + j) / 2.0
        pct = (avg_rank / max(n-1, 1)) * 100.0
        for k in range(i, j+1):
            ranks[idx[k]] = pct
        i = j + 1
    return ranks

def apply_primary_percentile_filter(straights: list[str], zones_str: str) -> list[str]:
    """
    Keep straights whose digit-sum percentile falls within any specified zone.
    If zones_str is empty or missing, keep all (default behavior).
    """
    zones = _parse_percentile_zones(zones_str)
    if not zones:
        return list(straights)
    sums = [sum(int(c) for c in s) for s in straights]
    pcts = _percentile_ranks(sums)
    kept = []
    for s, pct in zip(straights, pcts):
        ip = int(round(pct))
        if any(lo <= ip <= hi for (lo, hi) in zones):
            kept.append(s)
    return kept

def _load_primary_percentile_defaults() -> str:
    """
    Load default zones from model_defaults.PRIMARY_PERCENTILE_ZONES if available.
    If not found, return '' (no-op) to preserve behavior without exposing UI.
    """
    try:
        from model_defaults import PRIMARY_PERCENTILE_ZONES  # type: ignore
        if isinstance(PRIMARY_PERCENTILE_ZONES, str):
            return PRIMARY_PERCENTILE_ZONES
    except Exception:
        pass
    return ""  # safe fallback (keep-all)

# =========================
# Full enumeration (ALL 5-digit boxes, no prejudice)
# =========================
def all_boxes_full_enumeration() -> list[str]:
    """
    Return EVERY 5-digit combination of 0–9 in BOX form (sorted string, repetitions allowed).
    This is C(10+5-1, 5) = C(14,5) = 2,002 unique boxes.
    """
    boxes = []
    for comb in combinations_with_replacement(range(10), 5):
        boxes.append(''.join(str(d) for d in comb))  # already nondecreasing (box)
    return boxes  # length == 2002

# =========================
# Streamlit App
# =========================
def main():
    filters = load_filters()

    st.sidebar.header("🔢 DC-5 Filter Tracker Full")
    select_all = st.sidebar.checkbox("Select/Deselect All Filters", value=True)

    seed = st.sidebar.text_input(
        "Draw 1-back (required):",
        help="Enter the draw immediately before the combo to test"
    ).strip()
    prev_seed = st.sidebar.text_input(
        "Draw 2-back (optional):",
        help="Enter the draw two draws before the combo"
    ).strip()
    prev_prev = st.sidebar.text_input(
        "Draw 3-back (optional):",
        help="Enter the draw three draws before the combo"
    ).strip()

    # === UPDATED UI: Pair Groups (min 1, max 20) ===
    pair_group_a_str = st.sidebar.text_input(
        "Pair Group A (comma-separated two-digit pairs)",
        help="Example: 01,27,56  (min 1, max 20)"
    ).strip()
    pair_group_b_str = st.sidebar.text_input(
        "Pair Group B (comma-separated two-digit pairs)",
        help="Example: 67,89,12  (min 1, max 20)"
    ).strip()

    # No UI for Primary Percentile Zones — it uses internal defaults only.

    hot_input = st.sidebar.text_input("Hot digits (comma-separated):").strip()
    cold_input = st.sidebar.text_input("Cold digits (comma-separated):").strip()
    check_combo = st.sidebar.text_input("Check specific combo:").strip()
    hide_zero = st.sidebar.checkbox("Hide filters with 0 initial eliminations", value=True)

    if len(seed) != 5 or not seed.isdigit():
        st.sidebar.error("Draw 1-back must be exactly 5 digits")
        return

    # Build context (unchanged)
    seed_digits = [int(d) for d in seed]
    prev_digits = [int(d) for d in prev_seed if d.isdigit()]
    prev_prev_digits = [int(d) for d in prev_prev if d.isdigit()]
    new_digits = set(seed_digits) - set(prev_digits)
    hot_digits = [int(x) for x in hot_input.split(',') if x.strip().isdigit()]
    cold_digits = [int(x) for x in cold_input.split(',') if x.strip().isdigit()]
    due_digits = [d for d in range(10) if d not in prev_digits and d not in prev_prev_digits]
    seed_counts = Counter(seed_digits)
    seed_vtracs = set(V_TRAC_GROUPS[d] for d in seed_digits)
    seed_sum = sum(seed_digits)
    prev_sum_cat = sum_category(seed_sum)
    prev_pattern = []
    for digs in (prev_prev_digits, prev_digits, seed_digits):
        parity = 'Even' if sum(digs) % 2 == 0 else 'Odd'
        prev_pattern.extend([sum_category(sum(digs)), parity])
    prev_pattern = tuple(prev_pattern)

    def g
