"""Offline execution of selected unmodified pinned upstream definitions.

This is an explicit fallback for selector replay, NOT a LightRAG server. Only
the scheduling wrapper is synchronous; selector, renderer and tokenizer bodies
are compiled unchanged from the previously verified image snapshot.
"""
import ast
import asyncio
from dataclasses import dataclass
import hashlib
import json
import logging
import math
from pathlib import Path
import sys
import time
from types import ModuleType, SimpleNamespace
from typing import Protocol

SNAPSHOT = Path(__file__).resolve().parents[1]/'evaluation/diagnostics/20261016T044508Z_38dfaa7a_utils.py.txt'
EXPECTED_SHA256 = '70fe8389a462a3ada44df7d2dd7c49ed85a5c959ca32422f78ac8fdb2dafd5fc'
NAMES = {'TokenBudgetError', 'TokenSpan', 'TokenizerInterface', 'Tokenizer', 'TiktokenTokenizer',
         '_rendered_prefix_item_count', 'truncate_list_by_token_size', 'normalize_rerank_result',
         'apply_rerank_if_enabled', 'process_chunks_unified', 'generate_reference_list_from_chunks',
         'render_chunks_context_text', '_truncate_chunks_for_unified_context'}


async def sequential_executor(function, *args):
    return function(*args)


def load_selector(path=SNAPSHOT):
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != EXPECTED_SHA256:
        raise ValueError('Pinned upstream snapshot hash mismatch')
    tree = ast.parse(raw.decode('utf-8'))
    definitions = [node for node in tree.body if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
                   and node.name in NAMES]
    if {node.name for node in definitions} != NAMES:
        raise ValueError('Pinned definitions missing')
    module = ModuleType('_doctrace_verified_native_selector')
    sys.modules[module.__name__] = module
    module.__dict__.update(dataclass=dataclass, Protocol=Protocol, json=json, math=math,
        logger=logging.getLogger('doctrace.offline.selector'), DEFAULT_MAX_TOTAL_TOKENS=40000,
        run_in_tokenizer_executor=sequential_executor)
    header = ast.parse('from __future__ import annotations').body
    code = compile(ast.Module(body=header+definitions, type_ignores=[]), str(path), 'exec')
    exec(code, module.__dict__)
    return module


async def replay_rows(rows):
    native = load_selector()
    output = []
    tokenizers = {}
    for row in rows:
        if row['tokenizer'] not in tokenizers:
            tokenizers[row['tokenizer']] = native.TiktokenTokenizer(row['tokenizer'])
        tokenizer = tokenizers[row['tokenizer']]
        original = row['variants']['B0']
        async def reranker(query, documents, top_n=None):
            assert documents == [chunk['content'] for chunk in original]
            return row['scores'][:top_n] if top_n else row['scores']
        measured = {'case_id': row['case_id'], 'variants': {}}
        for name in ('B0', 'B1', 'B2', 'B3'):
            chunks = original if name == 'B1' else row['variants'][name]
            started = time.perf_counter()
            selected = await native.process_chunks_unified(row['query'], chunks,
                SimpleNamespace(chunk_top_k=row['top_k'], enable_rerank=name == 'B1'),
                {'tokenizer': tokenizer, 'rerank_model_func': reranker, 'min_rerank_score': 0},
                chunk_token_limit=row['budget'])
            _, rendered = native.generate_reference_list_from_chunks(selected)
            measured['variants'][name] = {'selected_ids': [chunk['chunk_id'] for chunk in selected],
                'rendered_chunk_tokens': len(tokenizer.encode(native.render_chunks_context_text(rendered))),
                'offline_selector_seconds': round(time.perf_counter()-started, 6)}
        output.append(measured)
    return output
