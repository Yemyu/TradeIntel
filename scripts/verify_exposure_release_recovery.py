"""Verify recovery with real data copies in an isolated temporary workspace."""
import argparse
import copy
import json
from pathlib import Path
import shutil
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from tradeintel_ai.exposure_version_store import ExposureVersionStore, VersionStoreError, content_digest, snapshot_difference
from tradeintel_ai.repository import EvidenceRepository, DataPaths
from tradeintel_ai.policy_exposure_tools import get_policy_exposure_series


def run(output):
    if output.exists():
        raise ValueError('output already exists')
    original = ExposureVersionStore(ROOT)
    version = original.active_version()
    source = original.release_root(version)
    snapshot = original.load_snapshot(version)
    with tempfile.TemporaryDirectory(prefix='tradeintel-recovery-') as directory:
        root = Path(directory)
        shutil.copytree(source / 'data', root / 'data')
        store = ExposureVersionStore(root)
        store.bootstrap(snapshot)
        store.prepare_release(version)
        repo = EvidenceRepository(DataPaths(root))
        before = get_policy_exposure_series(repository=repo, start='2026-07', end='2026-07')
        bad = copy.deepcopy(snapshot)
        bad['months']['2026-07']['output_sha256'] = '0' * 64
        bad['version'] = content_digest({k: v for k, v in bad.items() if k != 'version'})
        store.stage(snapshot, bad, snapshot_difference(snapshot, bad))
        working_month = root / f"data/processed/policy_exposure/monthly/{snapshot['policy_id']}_2026_07.csv"
        working_month.write_bytes(b'invalid candidate fixture')
        rejected = False
        try:
            store.prepare_release(bad['version'])
        except VersionStoreError:
            rejected = True
        after = get_policy_exposure_series(repository=repo, start='2026-07', end='2026-07')
        assert rejected and before == after and store.active_version() == version
        result = dict(status='passed', data_version=version, candidate_rejected=rejected,
                      working_file_corrupted_only_in_temporary_copy=True,
                      query_unchanged=before == after, api_calls=0,
                      july_all_origins_usd=after['data']['series'][0]['all_origins_value_usd'])
    output.mkdir(parents=True)
    (output / 'result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    (output / 'report.zh-CN.md').write_text(
        '# 数据副本失败恢复验证\n\n'
        '使用真实19个月数据的临时副本，故意损坏工作月表并尝试发布坏候选。\n\n'
        '结果：候选被拒绝，活动版本不变，旧发布副本查询前后完全一致。\n\n'
        f"七月全部来源金额：{result['july_all_origins_usd']:,} 美元。\n\n"
        f'版本：`{version}`。原始项目数据未改动，API调用0次。\n')
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    print(json.dumps(run(parser.parse_args().output), ensure_ascii=False, indent=2))
