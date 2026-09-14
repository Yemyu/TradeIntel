"""Build candidate policy evidence only; no activation or model calls."""
import json
from pathlib import Path
import sys
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'src'))
from tradeintel_ai.solar_policy import build_corpus

if __name__ == '__main__':
    corpus = build_corpus(ROOT)
    path = ROOT/'data/candidates/solar2024/policy_corpus.json'
    path.write_text(json.dumps(corpus, ensure_ascii=False, indent=2)+'\n')
    print(json.dumps({'status':corpus['status'],'chunks':len(corpus['chunks']),'path':str(path)}))
