"""
Measure funding extraction against hand-labelled articles.

    python scripts/evaluate_extraction.py            # data/eval/funding_labels.json

For each labelled article the extractor is run fresh (one model call each)
and compared field by field:
    is_funding_round   accuracy, plus precision/recall on the positive class
    company            exact after name normalisation, on true positives
    amount_usd         within 5% (or both null), on true positives with a label
    round              exact, on true positives where the label names a round
"""

import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import argparse
import json
import logging

from bson import ObjectId

from src.config import PROJECT_ROOT
from src.corpus.identity import name_key
from src.database.mongo_client import MongoDBClient
from src.extraction.funding import (PROMPT, ROUND_NAMES, SYSTEM_PROMPT, ExtractedRound,
                                    amount_usd, confidence_for)
from src.llm.groq_client import GroqClient
from src.search.document_text import normalize_whitespace

logging.basicConfig(level=logging.WARNING)
LABELS = os.path.join(PROJECT_ROOT, 'data', 'eval', 'funding_labels.json')


def extract_one(llm, article):
    title = article.get('title') or ''
    text = normalize_whitespace(f"{title}. {article.get('description') or ''}")[:1500]
    raw = llm.generate_json(prompt=PROMPT.format(title=title, text=text, rounds=', '.join(ROUND_NAMES)),
                            system_prompt=SYSTEM_PROMPT, temperature=0.0)
    extracted = ExtractedRound.model_validate(raw)
    return extracted, confidence_for(extracted, text)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--labels', default=LABELS)
    parser.add_argument('--verbose', action='store_true')
    args = parser.parse_args()

    with open(args.labels) as f:
        labels = json.load(f)['labels']

    mongo = MongoDBClient()
    llm = GroqClient()
    print("=" * 78)
    print(f"FUNDING EXTRACTION EVALUATION  {len(labels)} labelled articles  model={llm.model}")
    print("=" * 78)

    tp = fp = fn = tn = 0
    company_ok = company_n = amount_ok = amount_n = round_ok = round_n = 0
    confidences = {}
    missing = []

    for label in labels:
        article = mongo.db.documents.find_one({'_id': ObjectId(label['doc_id'])})
        if article is None:
            missing.append(label['doc_id'])
            continue
        extracted, confidence = extract_one(llm, article)
        predicted = bool(extracted.is_funding_round and extracted.company)
        truth = label['is_funding_round']

        if predicted and truth:
            tp += 1
            confidences[confidence] = confidences.get(confidence, 0) + 1
            if label.get('company'):
                company_n += 1
                company_ok += name_key(extracted.company) == name_key(label['company'])
            if 'amount_usd' in label:
                amount_n += 1
                got = amount_usd(extracted.amount, extracted.currency)
                want = label['amount_usd']
                if want is None and got is None:
                    amount_ok += 1
                elif want and got and abs(got - want) <= 0.05 * want:
                    amount_ok += 1
            if label.get('round'):
                round_n += 1
                round_ok += (extracted.round == label['round'])
        elif predicted and not truth:
            fp += 1
        elif not predicted and truth:
            fn += 1
        else:
            tn += 1

        if args.verbose:
            mark = 'ok ' if predicted == truth else 'XX '
            print(f"  {mark} truth={truth!s:<5} pred={predicted!s:<5} {confidence:<6} "
                  f"{(extracted.company or '-')[:22]:<22} {str(amount_usd(extracted.amount, extracted.currency) or '-'):>12} "
                  f"{(extracted.round or '-'):<9} | {(article.get('title') or '')[:60]}")

    n = tp + fp + fn + tn
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    print(f"\n  is_funding_round   accuracy {((tp + tn) / n if n else 0):.3f}   "
          f"precision {precision:.3f}   recall {recall:.3f}   (tp={tp} fp={fp} fn={fn} tn={tn})")
    print(f"  company            {company_ok}/{company_n} = {(company_ok / company_n if company_n else 0):.3f}")
    print(f"  amount_usd (±5%)   {amount_ok}/{amount_n} = {(amount_ok / amount_n if amount_n else 0):.3f}")
    print(f"  round              {round_ok}/{round_n} = {(round_ok / round_n if round_n else 0):.3f}")
    print(f"  confidence on true positives: {confidences}")
    if missing:
        print(f"\n  WARNING: {len(missing)} labelled articles not found in this database")
    mongo.close()


if __name__ == '__main__':
    main()
