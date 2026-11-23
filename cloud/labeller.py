import argparse
from collections import Counter
from io import BytesIO
import json
import os
from pathlib import Path
import time
from urllib.error import HTTPError
from urllib.parse import quote, urlencode, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

MODEL = 'google/owlv2-base-patch16-ensemble'
REVISION = 'cfd3195ba4ea9592eec887ded089f4c08eff231d'
MODEL_VERSION = f'{MODEL}@{REVISION}+backyard-v1'
PROMPTS = {
    'person': ('person',),
    'bird': ('bird', 'pigeon'),
    'cat': ('domestic cat',),
    'dog': ('domestic dog',),
    'fox': ('red fox',),
    'squirrel': ('squirrel',),
    'hedgehog': ('hedgehog',),
    'other animal': ('badger', 'deer', 'rabbit', 'rat'),
    'vehicle': ('car', 'van', 'truck', 'bicycle', 'motorcycle'),
}
MIN_SCORE = 0.18
PERSON_SCORE = 0.12
MAX_BYTES = 8 * 1024 * 1024
MAX_PIXELS = 16_000_000
MAX_ATTEMPTS = 3
BATCH_SIZE = 32


def pick_label(scores):
    if scores['person'] >= PERSON_SCORE:
        return 'person', scores['person']
    label = max(scores, key=scores.get)
    score = scores[label]
    return (label, score) if score >= MIN_SCORE else ('nothing', 1 - score)


def visibility(label, trigger):
    if label == 'person':
        return 'needs_review'
    if label == 'nothing' and trigger == 'motion':
        return 'false_trigger'
    return 'visible'


class Detector:
    def __init__(self):
        import torch
        from transformers import Owlv2ForObjectDetection, Owlv2Processor

        torch.set_num_threads(min(4, os.cpu_count() or 1))
        self.torch = torch
        self.processor = Owlv2Processor.from_pretrained(MODEL, revision=REVISION, use_fast=False)
        self.model = Owlv2ForObjectDetection.from_pretrained(
            MODEL, revision=REVISION, use_safetensors=True
        ).eval()
        self.labels = [label for label, prompts in PROMPTS.items() for _ in prompts]
        self.text = self.processor(text=[[f'a photo of a {prompt}' for prompts in PROMPTS.values()
                                          for prompt in prompts]], return_tensors='pt')

    def __call__(self, jpeg):
        from PIL import Image, ImageOps

        with Image.open(BytesIO(jpeg), formats=['JPEG']) as source:
            if source.width * source.height > MAX_PIXELS:
                raise ValueError('JPEG exceeds pixel limit')
            image = ImageOps.exif_transpose(source).convert('RGB')
        inputs = self.processor(images=image, return_tensors='pt')
        with self.torch.inference_mode():
            logits = self.model(**self.text, **inputs).logits[0]
            probabilities = logits.sigmoid().amax(dim=0).tolist()
        scores = dict.fromkeys(PROMPTS, 0.0)
        for label, score in zip(self.labels, probabilities):
            scores[label] = max(scores[label], score)
        return pick_label(scores)


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class Supabase:
    def __init__(self, base, key):
        url = urlsplit(base)
        if not url.hostname or (url.scheme != 'https' and not
                                (url.scheme == 'http' and url.hostname in ('127.0.0.1', 'localhost'))):
            raise ValueError('Supabase URL must use HTTPS outside local development')
        self.base = base.rstrip('/')
        self.headers = {'apikey': key}
        if key.count('.') == 2:
            self.headers['Authorization'] = f'Bearer {key}'
        self.opener = build_opener(NoRedirect())

    def request(self, path, payload=None, jpeg=False):
        request = Request(self.base + path, headers=self.headers)
        if payload is not None:
            request.method = 'PATCH'
            request.add_header('Content-Type', 'application/json')
            request.add_header('Prefer', 'return=minimal')
            request.data = json.dumps(payload).encode()
        with self.opener.open(request, timeout=20) as response:
            raw = response.read(MAX_BYTES + 1 if jpeg else -1)
        if jpeg:
            if len(raw) > MAX_BYTES:
                raise ValueError('JPEG exceeds storage size limit')
            return raw
        return json.loads(raw) if raw else None

    def pending(self):
        return self.request('/rest/v1/captures?' + urlencode({
            'select': 'id,object_path,trigger,label_attempts',
            'label': 'is.null',
            'label_attempts': f'lt.{MAX_ATTEMPTS}',
            'order': 'label_attempts.asc,received_at.asc,id.asc',
            'limit': BATCH_SIZE,
        }))

    def download(self, path):
        return self.request('/storage/v1/object/backyard-images/' + quote(path), jpeg=True)

    def update(self, row, payload):
        self.request('/rest/v1/captures?' + urlencode({
            'id': f'eq.{row["id"]}', 'label': 'is.null',
            'label_attempts': f'eq.{row["label_attempts"]}',
        }), payload)


def label_pending(store, detector_factory=Detector):
    rows = store.pending()
    if not rows:
        print('No eligible captures')
        return
    classify = detector_factory()
    counts = Counter()
    for position, row in enumerate(rows, start=1):
        start = time.monotonic()
        try:
            label, confidence = classify(store.download(row['object_path']))
        except Exception as error:
            if isinstance(error, HTTPError) and error.code in (401, 403):
                raise
            attempts = row['label_attempts'] + 1
            store.update(row, {'label_attempts': attempts})
            print(f'Capture {position}: {type(error).__name__} ({attempts}/{MAX_ATTEMPTS})', flush=True)
            counts['failed'] += 1
            continue
        store.update(row, {'label': label, 'label_confidence': confidence, 'label_model': MODEL_VERSION,
                           'label_visibility': visibility(label, row['trigger'])})
        counts[label] += 1
        print(f'Capture {position}: {label} ({time.monotonic() - start:.2f}s)', flush=True)
    print('Batch:', dict(counts))


def dry_run(paths):
    classify = Detector()
    counts = Counter()
    start = time.monotonic()
    for path in paths:
        before = time.monotonic()
        try:
            with path.open('rb') as jpeg:
                data = jpeg.read(MAX_BYTES + 1)
            if len(data) > MAX_BYTES:
                raise ValueError('JPEG exceeds storage size limit')
            label, confidence = classify(data)
            counts[label] += 1
            print(f'{path.name}: {label} {confidence:.3f} ({time.monotonic() - before:.2f}s)', flush=True)
        except Exception as error:
            counts['failed'] += 1
            print(f'{path.name}: {type(error).__name__}', flush=True)
    print(f'Dry run: {dict(counts)}; {(time.monotonic() - start) / len(paths):.2f}s/image')
    return bool(counts['failed'])


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--dry-run', nargs='+', type=Path, metavar='JPEG')
    args = parser.parse_args()
    if args.dry_run:
        return dry_run(args.dry_run)
    label_pending(Supabase(os.environ['SUPABASE_URL'], os.environ['SUPABASE_SECRET_KEY']))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
