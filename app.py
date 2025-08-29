# app.py
import streamlit as st
from itertools import permutations, combinations_with_replacement
import csv, os
from collections import Counter

# ===== Static mappings (unchanged) =====
V_TRAC_GROUPS = {0:1,5:1,1:2,6:2,2:3,7:3,3:4,8:4,4:5,9:5}
MIRROR = {0:5,5:0,1:6,6:1,2:7,7:2,3:8,8:3,4:9,9:4}

def sum_category(total: int) -> str:
    if 0 <= total <= 15:  return 'Very Low'
    if 16 <= total <= 24: return 'Low'
    if 25 <= total <= 33: return 'Mid'
    return 'High'

def load_filters(path: str='lottery_filters_batch10.csv') -> list:
    if not os.path.exists(path):
        st.error(f"Filter file not found: {path}")
        st.stop()
    filters = []
    # utf-8-sig strips a possible BOM; restkey captures overflow fields (from trailing commas)
    with open(path, newline='', encoding='utf-8-sig') as f:
        reader = csv.DictReader(f, skipinitialspace=True, restkey="_extra")
        for raw in reader:
            # >>> The ONLY behavioral change: skip None/blank header keys when lowercasing
            row = {str(k).lower(): v
                   for k, v in raw.items()
                   if k is not None and str(k).strip() != ""}

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
                st.error(f"Syntax error in filter {row.get('id','')}: {e}")
                continue
            row['enabled_default'] = row.get('enabled', '').lower() == 'true'
            filters.append(row)
    return filters

# ===== Pair parsing & generation =====
def _clean_pairs(raw: str):
    items = [p.strip() for p in (raw or "").split(",") if p.strip()]
    return [p for p in items if len(p)==2 and p.isdigit()]

def _unique_permutations(s: str):
    seen = set()
    for tup in permutations(s, 5):
        cand = ''.join(tup)
        if cand not in seen:
            seen.add(cand)
            yield cand

def generate_permutation_pool(seed: str, group_a: list[str], group_b: list[str]) -> list[str]:
    pool = set()
    for sd in seed:
        if not sd.isdigit(): continue
        for a in group_a:
            for b in group_b:
                base = sd + a + b
                if len(base)==5 and base.isdigit():
                    for perm in _unique_permutations(base):
                        pool.add(perm)
    return sorted(pool)

# ===== Primary Percentile (fixed zones; union of local OR global) =====
PRIMARY_PERCENTILE_ZONES = "0-26,30-35,36-43,50-60,60-70,80-83,93-94"

def _parse_zones(zs: str):
    zs = zs.replace('–','-')
    out = []
    for part in zs.split(','):
        part = part.strip()
        if '-' in part:
            a,b = part.split('-',1)
            try:
                lo,hi = int(a), int(b)
                if lo<=hi: out.append((lo,hi))
            except: pass
    return out

ZONES = _parse_zones(PRIMARY_PERCENTILE_ZONES)

def _percentile_ranks(values):
    n = len(values)
    if n==0: return []
    idx = list(range(n))
    idx.sort(key=lambda i: values[i])
    ranks = [0.0]*n
    i=0
    while i<n:
        j=i
        while j+1<n and values[idx[j+1]]==values[idx[i]]:
            j+=1
        avg = (i+j)/2.0
        pct = (avg / max(n-1,1)) * 100.0
        for k in range(i, j+1):
            ranks[idx[k]]=pct
        i=j+1
    return ranks

def _in_any_zone(pct: int) -> bool:
    return any(lo<=pct<=hi for (lo,hi) in ZONES)

# ===== Full enumeration (global boxes) =====
def all_boxes_full_enumeration() -> list[str]:
    return [''.join(str(d) for d in comb) for comb in combinations_with_replacement(range(10),5)]

def build_global_box_percentiles():
    boxes = all_boxes_full_enumeration()
    sums  = [sum(int(c) for c in b) for b in boxes]
    pcts  = _percentile_ranks(sums)
    return {b:int(round(p)) for b,p in zip(boxes,pcts)}  # box -> 0..100

GLOBAL_BOX_PCT = None  # lazy init

# ===== App =====
def main():
    global GLOBAL_BOX_PCT
    filters = load_filters()  # ← uses your exact loader

    st.sidebar.header("🔢 DC-5 Filter Tracker Full")
    select_all = st.sidebar.checkbox("Select/Deselect All Filters", value=True)

    seed = st.sidebar.text_input("Draw 1-back (required):", help="Enter the draw immediately before the combo to test").strip()
    prev_seed = st.sidebar.text_input("Draw 2-back (optional):", help="Enter the draw two draws before the combo").strip()
    prev_prev = st.sidebar.text_input("Draw 3-back (optional):", help="Enter the draw three draws before the combo").strip()

    # New inputs only: Pair Groups
    pair_group_a_str = st.sidebar.text_input("Pair Group A (comma-separated two-digit pairs)", help="Example: 01,27,56  (min 1, max 20)").strip()
    pair_group_b_str = st.sidebar.text_input("Pair Group B (comma-separated two-digit pairs)", help="Example: 67,89,12  (min 1, max 20)").strip()

    hot_input  = st.sidebar.text_input("Hot digits (comma-separated):").strip()
    cold_input = st.sidebar.text_input("Cold digits (comma-separated):").strip()
    check_combo = st.sidebar.text_input("Check specific combo:").strip()
    hide_zero   = st.sidebar.checkbox("Hide filters with 0 initial eliminations", value=True)

    if len(seed)!=5 or not seed.isdigit():
        st.sidebar.error("Draw 1-back must be exactly 5 digits")
        return

    # Context (unchanged)
    seed_digits = [int(d) for d in seed]
    prev_digits = [int(d) for d in prev_seed if d.isdigit()]
    prev_prev_digits = [int(d) for d in prev_prev if d.isdigit()]
    new_digits = set(seed_digits) - set(prev_digits)
    hot_digits  = [int(x) for x in hot_input.split(',')  if x.strip().isdigit()]
    cold_digits = [int(x) for x in cold_input.split(',') if x.strip().isdigit()]
    due_digits  = [d for d in range(10) if d not in prev_digits and d not in prev_prev_digits]
    seed_counts = Counter(seed_digits)
    seed_vtracs = set(V_TRAC_GROUPS[d] for d in seed_digits)
    seed_sum    = sum(seed_digits)
    prev_sum_cat = sum_category(seed_sum)
    prev_pattern=[]
    for digs in (prev_prev_digits, prev_digits, seed_digits):
        parity = 'Even' if sum(digs)%2==0 else 'Odd'
        prev_pattern.extend([sum_category(sum(digs)), parity])
    prev_pattern = tuple(prev_pattern)

    def gen_ctx(cdigits):
        csum = sum(cdigits)
        return {
            'seed_digits': seed_digits,
            'prev_seed_digits': prev_digits,
            'prev_prev_seed_digits': prev_prev_digits,
            'new_seed_digits': new_digits,
            'prev_pattern': prev_pattern,
            'hot_digits': hot_digits,
            'cold_digits': cold_digits,
            'due_digits': due_digits,
            'seed_counts': seed_counts,
            'seed_sum': seed_sum,
            'prev_sum_cat': prev_sum_cat,
            'combo_digits': cdigits,
            'combo_sum': csum,
            'combo_sum_cat': sum_category(csum),
            'seed_vtracs': seed_vtracs,
            'combo_vtracs': set(V_TRAC_GROUPS[d] for d in cdigits),
            'mirror': MIRROR,
            'common_to_both': set(seed_digits) & set(prev_digits),
            'last2': set(seed_digits) | set(prev_digits),
            'Counter': Counter
        }

    # Parse pair groups
    pair_group_a = _clean_pairs(pair_group_a_str)
    pair_group_b = _clean_pairs(pair_group_b_str)
    if len(pair_group_a)<1:
        st.sidebar.error("Pair Group A must contain at least 1 valid two-digit pair.")
        return
    if len(pair_group_b)<1:
        st.sidebar.error("Pair Group B must contain at least 1 valid two-digit pair.")
        return
    if len(pair_group_a)>20: pair_group_a = pair_group_a[:20]
    if len(pair_group_b)>20: pair_group_b = pair_group_b[:20]

    # 1) Generate all straights
    straights = generate_permutation_pool(seed, pair_group_a, pair_group_b)

    # 2) Primary Percentile (union: local OR global)
    local_sums = [sum(int(c) for c in s) for s in straights]
    local_pcts = _percentile_ranks(local_sums)
    local_keep = {s for s,p in zip(straights, local_pcts) if _in_any_zone(int(round(p)))}

    if GLOBAL_BOX_PCT is None:
        GLOBAL_BOX_PCT = build_global_box_percentiles()
    global_keep = {s for s in straights if _in_any_zone(GLOBAL_BOX_PCT.get(''.join(sorted(s)), 0))}

    straights_after_ppf = sorted(local_keep | global_keep)

    # 3) Deduplicate to boxes
    boxes = sorted({''.join(sorted(s)) for s in straights_after_ppf})

    # 4) Full enumeration comparison (after dedup; before manual filters)
    full_boxes = set(all_boxes_full_enumeration())  # 2,002 total
    gen_boxes  = set(boxes)
    intersection = sorted(gen_boxes & full_boxes)
    missing     = sorted(full_boxes - gen_boxes)
    coverage_pct = (len(intersection) / len(full_boxes)) * 100.0 if full_boxes else 0.0

    st.sidebar.markdown(
        f"**Straights:** {len(straights):,} → After PPF (union): {len(straights_after_ppf):,} → "
        f"Dedup (Boxes): {len(boxes):,}"
    )
    st.sidebar.markdown(
        f"**Full Enumeration (Boxes):** 2,002 • Covered: {len(intersection):,} "
        f"({coverage_pct:.1f}%) • Missing: {len(missing):,}"
    )

    with st.expander("Full Enumeration Comparison (Boxes)"):
        c1,c2,c3 = st.columns(3)
        c1.metric("Your Boxes", len(gen_boxes))
        c2.metric("Universal Boxes", len(full_boxes))
        c3.metric("Coverage %", f"{coverage_pct:.1f}%")
        st.caption("‘Missing’ are valid 5-digit boxes not present in your generated pool after PPF & dedup.")
        st.write("Missing boxes (first 200):", missing[:200])

    # 5) Manual filters (unchanged)
    eliminated = {}
    survivors = []
    for combo in boxes:
        cdigits = [int(c) for c in combo]
        ctx = gen_ctx(cdigits)
        for flt in filters:
            key = f"filter_{flt['id']}"
            if not st.session_state.get(key, select_all and flt['enabled_default']):
                continue
            try:
                if not eval(flt['applicable_code'], ctx, ctx):
                    continue
                if eval(flt['expr_code'], ctx, ctx):
                    eliminated[combo] = flt['name']
                    break
            except:
                continue
        else:
            survivors.append(combo)

    st.sidebar.markdown(f"**Total Boxes:** {len(boxes)}  Elim: {len(eliminated)}  Remain: {len(survivors)}")

    if check_combo:
        norm = ''.join(sorted(check_combo))
        if norm in eliminated:
            st.sidebar.info(f"Combo {check_combo} eliminated by {eliminated[norm]}")
        elif norm in survivors:
            st.sidebar.success(f"Combo {check_combo} survived all filters")
        else:
            st.sidebar.warning("Combo not found in generated list")

    # Initial elimination counts
    init_counts = {flt['id']: 0 for flt in filters}
    for flt in filters:
        for combo in boxes:
            cdigits = [int(c) for c in combo]
            ctx = gen_ctx(cdigits)
            try:
                if eval(flt['applicable_code'], ctx, ctx) and eval(flt['expr_code'], ctx, ctx):
                    init_counts[flt['id']] += 1
            except:
                pass

    # Order & display
    sorted_filters = sorted(filters, key=lambda flt: (init_counts[flt['id']] == 0, -init_counts[flt['id']]))
    display_filters = [flt for flt in sorted_filters if init_counts[flt['id']] > 0] if hide_zero else sorted_filters

    st.markdown(f"**Initial Manual Filters Count:** {len(display_filters)}")

    # Dynamic elimination sequence
    pool = list(boxes)
    dynamic_counts = {}
    for flt in display_filters:
        key = f"filter_{flt['id']}"
        active = st.session_state.get(key, select_all and flt['enabled_default'])
        dc = 0
        survivors_pool = []
        if active:
            for combo in pool:
                cdigits = [int(c) for c in combo]
                ctx = gen_ctx(cdigits)
                try:
                    if eval(flt['applicable_code'], ctx, ctx) and eval(flt['expr_code'], ctx, ctx):
                        dc += 1
                    else:
                        survivors_pool.append(combo)
                except:
                    survivors_pool.append(combo)
        else:
            survivors_pool = pool.copy()
        dynamic_counts[flt['id']] = dc
        pool = survivors_pool

    st.header("🔧 Active Filters")
    for flt in display_filters:
        key = f"filter_{flt['id']}"
        ic = init_counts[flt['id']]
        dc = dynamic_counts.get(flt['id'], 0)
        label = f"{flt['id']}: {flt['name']} — {dc}/{ic} eliminated"
        st.checkbox(label, key=key, value=st.session_state.get(key, select_all and flt['enabled_default']))

    with st.expander("Show remaining combinations"):
        for c in survivors:
            st.write(c)

if __name__ == '__main__':
    main()
