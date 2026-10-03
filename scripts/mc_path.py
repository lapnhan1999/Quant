"""Path-based Monte Carlo for plan B tickets (BAO_CAO_CO_HOI_2026-10.md, section 3).

Usage: python3 scripts/mc_path.py [N_paths]   -> data/opportunity/mc_path_results.json
Ladders: L0 = sell 1/3 at T1 and T2, trail the rest (report v1); L1 = sell 1/3 at T1, trail 2/3;
L2 = no sale, T1 moves stop to breakeven and starts trailing; L3 = L2 + sell 1/2 at 2x avg cost (report v2).
HHV is dropped (its 3 mil goes to the safe layer, n2=23). '/allcond' = every entry condition passes.

Joint stationary block bootstrap of daily log returns (VN trading days, 2020-10..2026-10)
for SSI, DBC, NLG, HHV, VIX, BTC, ETH; preserves cross-correlation and fat tails.
Drift regimes: historical (raw), de-meaned + mu (annual) for 'neutral' / 'favorable'.
Each ticket: entry window, buy zone, fundamental-condition probability, stop rule,
ladder take-profit with trailing, deadline; then mark-to-market at day H.
"""
import numpy as np, pandas as pd, sys, json

H = 500                      # ~24 months of VN trading days
D0 = 20                      # earliest stock entry: after Q3 reports (~end Oct)
import os
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HIST = os.path.join(ROOT, 'data/snapshot/history') + '/'
OUT = os.path.join(ROOT, 'data/opportunity/mc_path_results.json')
names = ['SSI', 'DBC', 'NLG', 'HHV', 'VIX', 'BTC', 'ETH']
files = {'SSI': 'SSI', 'DBC': 'DBC', 'NLG': 'NLG', 'HHV': 'HHV', 'VIX': 'VIX',
         'BTC': 'Y_BTC-USD', 'ETH': 'Y_ETH-USD'}

def load():
    s = {}
    for k, f in files.items():
        df = pd.read_csv(HIST + f + '.csv', index_col=0, parse_dates=True)
        s[k] = df['close'].astype(float)
    vn = s['SSI'].index
    for k in ['BTC', 'ETH']:
        s[k] = s[k].reindex(vn, method='ffill')
    P = pd.DataFrame(s).loc['2020-10-02':].dropna()
    return P

P = load()
R = np.log(P).diff().dropna().values          # T x 7
T = R.shape[0]
P0 = P.iloc[-1].values

def bootstrap(N, rng, block=20):
    idx = np.empty((N, H), dtype=np.int64)
    start = rng.integers(0, T, N)
    cur = start.copy()
    for t in range(H):
        new = rng.random(N) < 1.0 / block
        cur = np.where(new, rng.integers(0, T, N), (cur + 1) % T)
        idx[:, t] = cur
    return idx

# ticket definitions (prices in report units). Each tier fills at the close of the first day the
# price is inside [lo, hi] (and <= cap) within [start, dl], if its condition draw passed.
# Approximations: NLG zones merged; DBC only tranche A; VIX tranche 2 needs Q4 report (day ~80).
TK = {
 'SSI': dict(sz=7, tiers=[dict(lo=20.4, hi=21.5, w=1.0, start=D0, pcond=0.70)], dl=120, stop=15.8, stop_rule='weekly',
             tp=[(26.0, 1/3), (30.0, 1/3)], trail=0.15, cost=0.0035),
 'DBC': dict(sz=5, tiers=[dict(lo=13.4, hi=14.8, w=0.5, start=D0, pcond=0.70), dict(lo=16.3, hi=16.8, w=0.5, start=D0, pcond=0.35)], dl=185, stop=11.0, stop_rule='2close',
             tp=[(18.75, 1/3), (22.75, 1/3)], trail=0.15, cost=0.0035),
 'NLG': dict(sz=4, tiers=[dict(lo=18.7, hi=19.5, w=0.5, start=D0, pcond=0.80), dict(lo=16.9, hi=17.8, w=0.5, start=D0, pcond=0.80)],
             dl=185, stop=15.0, stop_rule='2close', tp=[(26.5, 1/3), (31.5, 1/3)], trail=0.15, cost=0.0035),
 'HHV': dict(sz=3, tiers=[dict(lo=9.75, hi=10.3, w=1.0, start=D0, pcond=0.55)], dl=120, stop=8.3, stop_rule='2close',
             tp=[(11.0, 1/2), (13.0, 1/2)], trail=0.12, cost=0.0035),
 'VIX': dict(sz=3, tiers=[dict(lo=13.0, hi=13.5, w=0.5, start=D0, pcond=0.60), dict(lo=12.4, hi=13.5, w=0.5, start=80, pcond=0.40)],
             dl=185, stop=10.0, stop_rule='2close', tp=[(15.75, 1/3), (18.75, 1/3)], trail=0.20, cost=0.0035),
 'BTC': dict(sz=5, tiers=[dict(lo=0, hi=80000, w=0.4, start='lic', pcond=1.0), dict(lo=0, hi=70000, w=0.3, start='lic', pcond=1.0),
                          dict(lo=0, hi=62000, w=0.3, start='lic', pcond=1.0)], dl=185, stop=56000, stop_rule='weekly',
             tp=[(100000, 1/3), (123000, 1/3)], trail=0.20, cost=0.005),
 'ETH': dict(sz=3, tiers=[dict(lo=0, hi=2600, w=0.4, start='lic', pcond=1.0), dict(lo=0, hi=2200, w=0.3, start='lic', pcond=1.0),
                          dict(lo=0, hi=1850, w=0.3, start='lic', pcond=1.0)], dl=185, stop=1450, stop_rule='weekly',
             tp=[(3500, 0.30), (4650, 0.40)], trail=0.25, cost=0.005),
}

def ladder_variant(tk, variant):
    tk = dict(tk)
    if variant == 'L1':      # keep the tail: 1/3 at T1 (stop -> breakeven), 2/3 trailing, no T2 sale
        tk['tp'] = [(tk['tp'][0][0], 1/3)]
    elif variant == 'L2':    # no take-profit sale; T1 touch only moves stop to breakeven and starts trailing
        tk['tp'] = [(tk['tp'][0][0], 0.0)]
    elif variant == 'L3':    # like L2, plus sell 1/2 at 2x the average buy price (take the principal back)
        ws = sum(t['w'] for t in tk['tiers'])
        avg = sum(t['w'] * ((t['lo'] + t['hi']) / 2 if t['lo'] > 0 else t['hi'] * 0.97) for t in tk['tiers']) / ws
        tk['tp'] = [(tk['tp'][0][0], 0.0), (2 * avg, 0.5)]
        tk['trail_from'] = 0
    return tk

LIC_WAIT = 15  # do not buy in the first 2-4 weeks after a licensed exchange opens
YC = 0.07   # yield on cash released from tickets / waiting in bond fund
def sim_ticket(path, tk, rng, lic_day):
    N = path.shape[0]; sz = tk['sz']; c2 = tk['cost'] / 2
    tiers = []
    for ti in tk['tiers']:
        st = lic_day + LIC_WAIT if ti['start'] == 'lic' else np.full(N, ti['start'])
        tiers.append(dict(ti, st=st, cond=rng.random(N) < ti['pcond'], filled=np.zeros(N, bool)))
    inv = np.zeros(N); carry = np.zeros(N); raw = np.zeros(N); sh_bought = np.zeros(N); sh = np.zeros(N); proceeds = np.zeros(N)
    opened = np.zeros(N, bool); closed = np.zeros(N, bool); anytp = np.zeros(N, bool)
    t_in = np.full(N, H); t_loss = np.full(N, H)
    stop = np.full(N, float(tk['stop'])); peak = np.zeros(N); below = np.zeros(N, int)
    tp_hit = [np.zeros(N, bool) for _ in tk['tp']]; trailing_on = np.zeros(N, bool)
    stopped = np.zeros(N, bool)
    for t in range(H):
        p = path[:, t]
        # ---- exits for positions opened before today
        act = opened & (~closed) & (t > t_in)
        g = 1 + YC * (H - t) / 250          # growth of cash released today until horizon
        if act.any():
            peak = np.where(act, np.maximum(peak, p), peak)
            avgc = inv / np.maximum(sh_bought, 1e-12)
            for j, (lvl, frac) in enumerate(tk['tp']):
                hit = act & (~tp_hit[j]) & (p >= lvl)
                if hit.any():
                    q = np.where(hit, np.minimum(frac * sh_bought, sh), 0)
                    proceeds += q * lvl * (1 - c2) * g; raw += q * lvl * (1 - c2); sh -= q
                    tp_hit[j] |= hit; anytp |= hit
                    if j == 0:
                        stop = np.where(hit, np.maximum(stop, avgc), stop)
                    if j == tk.get('trail_from', len(tk['tp']) - 1):
                        trailing_on |= hit
            tr = act & trailing_on & (p <= peak * (1 - tk['trail'])) & (sh > 0)
            proceeds += np.where(tr, sh * p * (1 - c2) * g, 0); raw += np.where(tr, sh * p * (1 - c2), 0); sh = np.where(tr, 0, sh)
            if tk['stop_rule'] == 'weekly':
                trig = act & (t % 5 == 4) & (p < stop) & (sh > 0)
            else:
                below = np.where(act & (p < stop), below + 1, 0)
                trig = act & (below >= 2) & (sh > 0)
            proceeds += np.where(trig, sh * p * 0.99 * (1 - c2) * g, 0); raw += np.where(trig, sh * p * 0.99 * (1 - c2), 0)
            stopped |= trig & (~anytp)
            t_loss = np.where(trig & (t_loss == H) & (~anytp), t, t_loss)
            sh = np.where(trig, 0, sh)
            closed |= act & (sh <= 1e-12)
        # ---- entries (no new tiers once any TP hit or position closed)
        for ti in tiers:
            ok = (~ti['filled']) & ti['cond'] & (t >= ti['st']) & (t <= tk['dl']) & (p >= ti['lo']) & (p <= ti['hi']) \
                 & (~closed) & (~anytp)
            if ok.any():
                amt = sz * ti['w']
                inv += np.where(ok, amt, 0)
                carry += np.where(ok, amt * YC * t / 250 * (1 + YC * (H - t) / 250), 0)
                q = np.where(ok, amt * (1 - c2) / p, 0)
                sh_bought += q; sh += q
                t_in = np.where(ok & (~opened), t, t_in)
                opened |= ok; ti['filled'] |= ok
    mtm = np.where(opened & (~closed), sh * path[:, -1] * (1 - c2), 0); proceeds += mtm; raw += mtm
    return dict(inv=inv, proceeds=proceeds, raw=raw, carry=carry, t_in=t_in, t_loss=t_loss, filled=opened)

def run(N=20000, seed=7, drift='neutral', mu_vn=0.08, mu_c=0.08, variant='L0', breaker=12.0, pCake=0.30, drop=(), n2=20, pc=None,
        lic_lo=40, lic_hi=250, lic_p=0.65):
    rng = np.random.default_rng(seed)
    idx = bootstrap(N, rng)
    Rb = R[idx]                                  # N x H x 7
    if drift != 'hist':
        m = R.mean(axis=0)
        # target ARITHMETIC expected annual return mu: log drift = ln(1+mu)/250 - var/2
        mu = np.array([np.log(1 + mu_vn) / 250] * 5 + [np.log(1 + mu_c) / 250] * 2) - R.var(axis=0) / 2
        Rb = Rb - m + mu
    paths = P0 * np.exp(np.cumsum(Rb, axis=1))   # N x H x 7
    lic = np.where(rng.random(N) < (1.0 if pc is not None else lic_p), rng.integers(lic_lo, lic_hi, N), H + 1)
    res = {}
    for j, k in enumerate(names):
        tk = ladder_variant(TK[k], variant)
        if k in drop: tk = dict(tk, sz=0)
        if pc is not None: tk = dict(tk, tiers=[dict(t, pcond=pc) for t in tk['tiers']])
        res[k] = sim_ticket(paths[:, :, j], tk, rng, lic)
    # breaker: cancel entries that happen after cumulative realized stop-losses >= breaker
    order = np.argsort(np.stack([res[k]['t_in'] for k in names], 1), axis=1)
    # approximate: compute realized loss timeline from tickets that stop out
    loss_events = []
    for k in names:
        r = res[k]
        loss = np.maximum(r['inv'] - r['proceeds'], 0) * (r['t_loss'] < H)
        loss_events.append((r['t_loss'], loss))
    cancelled = {}
    for k in names:
        r = res[k]
        cum_before = np.zeros(N)
        for (tl, ls), k2 in zip(loss_events, names):
            if k2 == k: continue
            cum_before += np.where(tl < r['t_in'], ls, 0)
        cancelled[k] = r['filled'] & (cum_before >= breaker)
    # waiting money: bond fund 1st year ~7.3%, then deposit ~7.3% -> ~1.04 for the waiting period + reinvest
    r2 = np.clip(0.073 + 0.006 * rng.standard_normal(N), 0.06, 0.088)
    Mw = 1.040 * (1 + r2) * (1 + 0.4 * r2)
    r1 = np.where(rng.random(N) < pCake, 0.096, rng.uniform(0.080, 0.084, N))
    M1 = (1 + r1) * (1 + r2)
    rlock = np.clip(0.083 + 0.004 * rng.standard_normal(N), 0.078, 0.090)
    M2 = (1 + 0.07 * 2 / 12) * (1 + rlock) * (1 + r2 * 10 / 12)
    M3 = (1 + 0.072) ** 2
    safe = 40 * M1 + n2 * M2 + 10 * M3
    risk = np.zeros(N); out = {}
    for k in names:
        r = res[k]; sz = 0 if k in drop else TK[k]['sz']
        inv = np.where(cancelled[k], 0, r['inv']); pro = np.where(cancelled[k], 0, r['proceeds'] + r['carry'])
        # proceeds released before horizon earn ~deposit for remaining time: approx +7% * remaining/2y (ignored, small)
        val = pro + (sz - inv) * Mw
        risk += val
        m = np.where(inv > 0, np.where(cancelled[k], 0, r['raw']) / np.maximum(inv, 1e-9), np.nan)
        dep = inv > 0
        md = m[dep]                                   # realized multiples of tickets actually bought
        cond = lambda x: float(x.mean()) if md.size else float('nan')
        out[k] = dict(dep=dep.mean(), mean_mult=cond(md),
                      p_loss=cond(md < 1), p_l30=cond(md < 0.7), p_x15=cond(md >= 1.5), p_x2=cond(md >= 2),
                      u_p_loss=float((md < 1).sum()) / N, u_p_x2=float((md >= 2).sum()) / N,
                      ticket_ev=float(np.mean(val)) / sz if sz else float('nan'))
    tot = safe + risk
    bench = 100 * 1.09 * (1 + r2)
    q = np.percentile(tot, [5, 50, 95])
    port = dict(mean=tot.mean(), p5=q[0], med=q[1], p95=q[2], mn=tot.min(), p_loss=(tot < 100).mean(),
                p_ge120=(tot >= 120).mean(), p_ge130=(tot >= 130).mean(), p_ge150=(tot >= 150).mean(),
                p_x2=(tot >= 200).mean(), p_beat_A=(tot > bench).mean(), bench=bench.mean())
    return out, port

def job(args):
    drift, mv, mc, var, N, pc = args
    out, port = run(N=N, drift=drift, mu_vn=mv, mu_c=mc, variant=var, drop=('HHV',), n2=23, pc=pc)
    return f'{drift}/{var}' + ('/allcond' if pc else ''), dict(tickets=out, port=port)

if __name__ == '__main__':
    from multiprocessing import Pool
    N = int(sys.argv[1]) if len(sys.argv) > 1 else 20000
    regimes = [('bad', -0.05, -0.10), ('neutral', 0.08, 0.08), ('favorable', 0.18, 0.25), ('hist', 0, 0)]
    jobs = [(d, mv, mc, v, N, None) for d, mv, mc in regimes for v in ['L0', 'L1', 'L2', 'L3']]
    jobs += [('bad', -0.05, -0.10, 'L3', N, 1.0), ('crash', -0.25, -0.40, 'L3', N, 1.0), ('neutral', 0.08, 0.08, 'L3', N, 1.0)]
    with Pool(4) as pool:
        res = pool.map(job, jobs)
    allres = dict(res)
    for key, r in allres.items():
        print('====', key, ' '.join(f'{a}={b:.4f}' for a, b in r['port'].items()))
        for k, v in r['tickets'].items():
            print('   ', k.ljust(4), ' '.join(f'{a}={b:.3f}' for a, b in v.items()))
    json.dump(allres, open(OUT, 'w'), indent=1, default=float)
