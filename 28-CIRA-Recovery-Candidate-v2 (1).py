"""CIRA Phase 5.5 recovery candidate. Default action is read-only status.

Recovery requires --recover --confirm-local-recovery and is restricted to an
explicit --root. Never infer the production root from this file's location.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import tempfile

TICKERS = ('AAPL', 'MSFT')
REL = Path('reports/company-intelligence')
JOURNAL = '.phase55-promotion-journal.json'
LOCK = '.phase55-promotion.lock'


def sha(path):
    h = hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda: f.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def within(path, parent):
    return path == parent or parent in path.parents


def inspect(root):
    root = root.resolve(strict=True)
    journal_path = root / JOURNAL
    lock = root / LOCK
    result = {'root': str(root), 'journal_exists': journal_path.is_file(), 'lock_exists': lock.exists(), 'reports': {}, 'errors': []}
    if not journal_path.is_file():
        result['status'] = 'no_journal'
        return result
    try:
        j = json.loads(journal_path.read_text(encoding='utf-8'))
        if not isinstance(j, dict):
            raise ValueError('Journal must be a JSON object')
        result['status'] = j.get('status')
        result['run_id'] = j.get('run_id')
        backup_value = j.get('backup')
        if not isinstance(backup_value, str) or not backup_value:
            raise ValueError('Missing backup path')
        backup = Path(backup_value).resolve(strict=True)
        backup_base = (root / '.phase55-backups').resolve(strict=True)
        if not within(backup, backup_base) or backup == backup_base:
            raise ValueError('Backup path outside expected backup directory')
        if not isinstance(j.get('original_sha256'), dict) or not isinstance(j.get('staged_sha256'), dict):
            raise ValueError('Missing hash maps')
        for ticker in TICKERS:
            original_hash = j['original_sha256'].get(ticker)
            staged_hash = j['staged_sha256'].get(ticker)
            if not isinstance(original_hash, str) or not isinstance(staged_hash, str):
                raise ValueError('Missing report hashes: ' + ticker)
            live = root / REL / (ticker + '-company-intelligence.json')
            saved = backup / REL / (ticker + '-company-intelligence.json')
            if not saved.is_file() or not within(saved.resolve(), backup):
                raise ValueError('Missing or unsafe backup: ' + ticker)
            backup_hash = sha(saved)
            current_hash = sha(live) if live.is_file() else None
            result['reports'][ticker] = {
                'current_sha256': current_hash,
                'original_sha256': original_hash,
                'staged_sha256': staged_hash,
                'backup_sha256': backup_hash,
                'backup_valid': backup_hash == original_hash,
                'current_known': current_hash in (original_hash, staged_hash),
            }
        result['recovery_ready'] = (result['status'] in ('prepared', 'recovery_required', 'replacing_AAPL', 'replacing_MSFT', 'recovery_in_progress')
                                    and not result['lock_exists']
                                    and all(v['backup_valid'] and v['current_known'] for v in result['reports'].values()))
    except (OSError, ValueError, KeyError, TypeError) as exc:
        result['errors'].append(str(exc))
        result['recovery_ready'] = False
    return result


def recover(root):
    root = root.resolve(strict=True)
    lock = root / LOCK
    # Exclusive lock; never remove a pre-existing lock automatically.
    fd = os.open(str(lock), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    try:
        os.write(fd, str(os.getpid()).encode('ascii'))
        os.close(fd)
        fd = None
        # Inspect while holding the lock, but ignore our own lock in readiness.
        state = inspect(root)
        if state['errors'] or state.get('status') not in ('prepared', 'recovery_required', 'replacing_AAPL', 'replacing_MSFT', 'recovery_in_progress'):
            raise RuntimeError('Journal is not eligible for recovery: ' + str(state))
        if not all(v['backup_valid'] and v['current_known'] for v in state['reports'].values()):
            raise RuntimeError('Unexpected report content or invalid backup; manual review required')
        jpath = root / JOURNAL
        j = json.loads(jpath.read_text(encoding='utf-8'))
        backup = Path(j['backup']).resolve(strict=True)
        # Persist recovery intent before any replacement. A later invocation can
        # resume only after verifying both backups and every live report hash.
        j['status'] = 'recovery_in_progress'
        atomic_json(jpath, j)
        for ticker in TICKERS:
            destination = root / REL / (ticker + '-company-intelligence.json')
            expected = state['reports'][ticker]
            current = sha(destination) if destination.is_file() else None
            if current not in (expected['original_sha256'], expected['staged_sha256']):
                raise RuntimeError('Concurrent change detected: ' + ticker)
            if current == expected['original_sha256']:
                continue
            source = backup / REL / (ticker + '-company-intelligence.json')
            if sha(source) != expected['original_sha256']:
                raise RuntimeError('Backup changed: ' + ticker)
            temp = None
            try:
                with tempfile.NamedTemporaryFile(dir=destination.parent, prefix='.cira-recovery-', delete=False) as f:
                    temp = Path(f.name)
                    with source.open('rb') as inp:
                        shutil.copyfileobj(inp, f)
                    f.flush()
                    os.fsync(f.fileno())
                if sha(temp) != expected['original_sha256']:
                    raise RuntimeError('Temporary recovery hash mismatch: ' + ticker)
                os.replace(temp, destination)
                if sha(destination) != expected['original_sha256']:
                    raise RuntimeError('Post-replacement hash mismatch: ' + ticker)
            finally:
                if temp is not None:
                    temp.unlink(missing_ok=True)
        for ticker in TICKERS:
            destination = root / REL / (ticker + '-company-intelligence.json')
            if sha(destination) != state['reports'][ticker]['original_sha256']:
                raise RuntimeError('Final verification failed: ' + ticker)
        j['status'] = 'recovered'
        atomic_json(jpath, j)
        return {'status': 'recovered', 'root': str(root)}
    finally:
        if fd is not None:
            os.close(fd)
        lock.unlink(missing_ok=True)


def atomic_json(path, value):
    temp = None
    try:
        with tempfile.NamedTemporaryFile('w', encoding='utf-8', dir=path.parent, prefix='.cira-journal-', delete=False) as f:
            temp = Path(f.name)
            json.dump(value, f, indent=2)
            f.write('\n')
            f.flush()
            os.fsync(f.fileno())
        os.replace(temp, path)
    finally:
        if temp is not None:
            temp.unlink(missing_ok=True)


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--root', required=True, type=Path, help='Explicit sandbox or project root')
    p.add_argument('--recovery-status', action='store_true')
    p.add_argument('--recover', action='store_true')
    p.add_argument('--confirm-local-recovery', action='store_true')
    args = p.parse_args()
    if args.confirm_local_recovery and not args.recover:
        p.error('--confirm-local-recovery requires --recover')
    if args.recover and not args.confirm_local_recovery:
        p.error('Recovery requires --confirm-local-recovery')
    result = recover(args.root) if args.recover else inspect(args.root)
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
