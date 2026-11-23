"""Replay only the two untraced protocol failures from issue #285.

Use --root for an independently built, unchanged source checkout. No fixes
are combined. --guard adds an explicit sender TX guard to the event harness.
"""
import argparse
import dataclasses
import hashlib
import inspect
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys


def simple(x):
    if isinstance(x, bytes):
        return x.hex()
    if isinstance(x, dict):
        return {str(k): simple(v) for k, v in x.items()}
    if isinstance(x, (set, frozenset)):
        return [simple(v) for v in sorted(x)]
    if isinstance(x, (tuple, list)):
        return [simple(v) for v in x]
    if dataclasses.is_dataclass(x):
        return simple(dataclasses.asdict(x))
    return x


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--root', type=Path, required=True)
    ap.add_argument('--case', choices=['baseline', 'robust'], required=True)
    ap.add_argument('--guard', action='store_true')
    ap.add_argument('--harness-root', type=Path, help='checkout supplying linksim.run; modem/ARQ stay at --root')
    ap.add_argument('--out', type=Path, required=True)
    a = ap.parse_args()
    for name in ('OMP_NUM_THREADS', 'OPENBLAS_NUM_THREADS', 'MKL_NUM_THREADS', 'DATA2G_THREADS'):
        os.environ[name] = '1'
    root = a.root.resolve()
    sys.path[:0] = [str(root), str(root / 'tests'), str(root / 'scripts')]
    import native_subs
    n, why = native_subs.import_native()
    if n is None:
        raise RuntimeError(why)
    n.set_threads(1)
    native_subs.apply(native_subs.build(n, skip={'arq', 'gear'}))
    import linksim as L
    import phy_session as P
    from data2g.arq import link as LK, session as S

    rows = []
    clock = {'t': 0.0}
    bursts = {}

    def snap(s):
        if not s:
            return None
        out = {k: getattr(s, k) for k in ('direction', 'state', '_latest', '_confirmed', '_acted_on',
               '_stale', '_answered', '_abandon', '_abandon_bursts', '_abandon_epoch', '_peer_epoch')}
        out.update(tx_base=s.tx.base, tx_next=s.tx.next, tx_ack=s.tx.ack, rx_cum=s.rx.cum,
                   pending=s.tx.pending(), fail_reason=s.fail_reason)
        return simple(out)

    for name in ('poll', 'on_header', 'on_rx', 'on_tx_end', '_on_timeout'):
        orig = getattr(S.Session, name)
        def wrap(self, *args, _name=name, _orig=orig, **kw):
            now = args[0] if _name in ('poll', '_on_timeout') else args[-1]
            clock['t'] = now
            before = snap(self.station)
            out = _orig(self, *args, **kw)
            if _name != 'poll' or out is not None:
                rows.append(dict(kind='session_' + _name, t=now, who=self.call,
                                 mode=getattr(out if _name == 'poll' else args[0], 'submode', None),
                                 before=before, after=snap(self.station), state=self.state,
                                 reason=self.close_reason, deadline=self._deadline,
                                 build_at=self._build_at, wake=self._wake_time()))
            return out
        setattr(S.Session, name, wrap)
    for name in ('_take_ack', '_take_abandon', '_start_abandon'):
        orig = getattr(LK.Station, name)
        def wrap(self, *args, _name=name, _orig=orig, **kw):
            before = snap(self)
            try:
                out = _orig(self, *args, **kw)
            except Exception as e:
                rows.append(dict(kind=_name, t=clock['t'], who=self.direction, before=before,
                                 args=simple(args if _name != '_take_abandon' else args[1:]),
                                 error=str(e), after=snap(self)))
                raise
            rows.append(dict(kind=_name, t=clock['t'], who=self.direction, before=before,
                             args=simple(args if _name != '_take_abandon' else args[1:]),
                             after=snap(self)))
            return out
        setattr(LK.Station, name, wrap)

    class Phy(P.RealPhy):
        def send(self, b, t0):
            end, h, make_rx, meas = super().send(b, t0)
            sender = b.slots[0].mask_id[1] & 1
            overlaps = [r['index'] for r in rows if r['kind'] == 'send' and r['end'] > t0]
            row = dict(kind='send', index=sum(r['kind'] == 'send' for r in rows), t=t0, sender=sender, end=end,
                       header=simple(h), mode=b.submode, overlaps=overlaps,
                       slots=[dict(mask=simple(s.mask_id), rv=s.rv, payload=s.payload.hex()) for s in b.slots])
            bursts[id(b)] = row
            rows.append(row)
            if make_rx:
                old = make_rx
                def make_rx(*args):
                    r = old(*args)
                    rows.append(dict(kind='deliver_rx', t=clock['t'], send=row['index'], receiver=1-sender,
                                     after_rx_txend_pending=None))
                    return r
            return end, h, make_rx, meas

    harness = L
    if a.harness_root:
        spec = importlib.util.spec_from_file_location('replay_harness', a.harness_root / 'scripts/linksim.py')
        harness = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(harness)
    harness_source = inspect.getsource(harness.run)
    src = harness_source.replace('def run(', 'def run_drain(', 1)
    ack = ('all(s.state == S.CONNECTED and s.station is not None and not s._pending_write '
           'and not s.station.tx.pending() for s in (a,b))')
    src = src.replace('if all(x is not None for x in t_done):',
                      'if all(x is not None for x in t_done) and ' + ack + ':')
    src = src.replace('t = max(t, min(nxt))',
                      'if min(nxt) >= horizon:\n            t = horizon\n            break\n        t = max(t, min(nxt))')
    src = src.replace('return dict(t=t,', 'return dict(acknowledged=' + ack + ', t=t,')
    if a.guard:
        # Session is below the Engine: the caller must enforce half duplex.
        src = src.replace('if any(f <= t for f in hold[id(me)].values()):',
                          'if any(e[1] == "txend" and e[2] is me and e[0] > t for e in events) or any(f <= t for f in hold[id(me)].values()):')
        src = src.replace('if not any(f <= t for f in hold[id(s_)].values()))',
                          'if not any(e[1] == "txend" and e[2] is s_ and e[0] > t for e in events) and not any(f <= t for f in hold[id(s_)].values()))')
    ns = dict(L.__dict__)
    exec(compile(src, 'study-drain', 'exec'), ns)
    dop, delay, snr, seed = (1, 7, -10, 100033) if a.case == 'baseline' else (1, 2, -6, 100023)
    phy = Phy(P.ContinuousChannel('awgn', snr, seed, 180, doppler=dop, delay_ms=delay))
    result = ns['run_drain'](L.make_policy('shift+cpm'), L.make_policy('shift+cpm'), None,
                 [('a', 64, None, 0), ('b', 64, 0, .2)], seed=seed, horizon=180, phy=phy, cap=2)
    revision = subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=root, text=True, capture_output=True)
    output = dict(root_revision=revision.stdout.strip() if revision.returncode == 0 else None,
                  root_diff_sha256=hashlib.sha256(subprocess.check_output(['git', 'diff'], cwd=root)).hexdigest() if revision.returncode == 0 else None,
                  source_sha256={f:hashlib.sha256((root/f).read_bytes()).hexdigest() for f in ('scripts/linksim.py', 'scripts/phy_session.py', 'data2g/arq/link.py', 'data2g/arq/session.py', 'data2g/arq/policy.py')},
                  native_module_sha256=hashlib.sha256(Path(n.__file__).read_bytes()).hexdigest(),
                  script_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                  harness_source_sha256=hashlib.sha256(harness_source.encode()).hexdigest(),
                  args=vars(a) | {'root':str(root), 'out':str(a.out)}, result=result, trace=rows)
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(json.dumps(output, default=str, indent=2) + '\n')
    print(json.dumps(result, default=str), flush=True)


if __name__ == '__main__':
    main()
