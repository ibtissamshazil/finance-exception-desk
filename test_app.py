"""Run with: python -m unittest -v test_app.py."""

import copy
import json
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from http.client import IncompleteRead
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from app import FinanceAgent, Store, calculate_variance, load_env, make_server, money


class DemoFixture(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.data = json.loads(Path(__file__).with_name('sample_data.json').read_text(encoding='utf-8'))
        self.store = Store(Path(self.temp.name) / 'test.sqlite3')
        self.agent = FinanceAgent(self.data, self.store)


class AgentTests(DemoFixture):
    def test_sample_counts_and_exact_slide_case(self):
        self.assertEqual(len(self.data['invoices']), 10)
        self.assertEqual(len(self.data['purchase_orders']), 10)
        facts = self.agent.facts('INV-182')
        self.assertEqual(facts['variance_aed'], '3500.00')
        result = self.agent.review_case('INV-182')
        self.assertIn('3,500.00', result['review']['reason'])
        self.assertTrue(result['review']['needs_human_review'])
        self.assertFalse(result['payment_executed'])
        self.assertEqual(result['validation']['status'], 'passed')

    def test_decimal_and_invalid_money(self):
        self.assertEqual(calculate_variance('21500', '18000'), Decimal('3500.00'))
        self.assertEqual(calculate_variance('18000', '18000'), Decimal('0.00'))
        self.assertEqual(calculate_variance('0.30', '0.20'), Decimal('0.10'))
        self.assertEqual(money('1.005'), Decimal('1.01'))
        for value in [None, True, '-1', 'NaN', 'Infinity', 'missing', {}, []]:
            with self.subTest(value=value), self.assertRaises(ValueError):
                money(value)

    def test_duplicates_flag_both_records(self):
        for invoice_id in ['INV-184', 'INV-185']:
            self.assertIn('duplicate', self.agent.facts(invoice_id)['issue_codes'])

    def test_clean_missing_and_inconsistent_records(self):
        self.assertEqual(self.agent.facts('INV-183')['issue_codes'], [])
        self.assertEqual(self.agent.facts('INV-188')['issue_codes'], [])
        expected = {'INV-186': 'missing_approval', 'INV-187': 'ledger_mismatch',
                    'INV-189': 'missing_po', 'INV-190': 'supplier_mismatch', 'INV-191': 'invalid_amount'}
        for invoice_id, issue in expected.items():
            self.assertIn(issue, self.agent.facts(invoice_id)['issue_codes'])
        with self.assertRaises(ValueError):
            self.agent.get_invoice('../../private')
        with self.assertRaises(ValueError):
            self.agent.get_purchase_order('PO-UNKNOWN')

    def test_source_tools_return_copies(self):
        record = self.agent.get_invoice('INV-182')
        record['amount_aed'] = '1'
        self.assertEqual(self.agent.get_invoice('INV-182')['amount_aed'], '21500.00')

    def test_bad_model_output_falls_back_and_audits(self):
        for mode in ['broken_json', 'invented_amount']:
            result = self.agent.review_case('INV-182', mode)
            self.assertEqual(result['validation']['status'], 'fallback')
            self.assertIn('3,500.00', result['review']['reason'])
            self.assertTrue(result['validation']['errors'])
        events = self.store.audit()['events']
        self.assertEqual(len(events), 2)
        self.assertTrue(all(event['details']['validation']['status'] == 'fallback' for event in events))

    def test_rejects_unsupported_text_ids_flags_and_confidence(self):
        facts = self.agent.facts('INV-182')
        good = self.agent.draft(facts)
        for field, value in [('reason', 'Pay this invoice now.'), ('case_id', 'INV-999'),
                             ('needs_human_review', False), ('confidence', True),
                             ('confidence', float('nan')), ('confidence', 1.1),
                             ('evidence', [{'source': 'invented', 'value': '1'}])]:
            candidate = copy.deepcopy(good)
            candidate[field] = value
            with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                self.agent.validate_review(candidate, facts)

    def test_live_adapter_uses_schema_and_validates_result(self):
        draft = self.agent.draft(self.agent.facts('INV-182'))
        reply = {'status': 'completed', 'model': 'mock-model-v1', 'output': [
            {'type': 'message', 'content': [{'type': 'output_text', 'text': json.dumps(draft)}]}]}
        with patch.dict('os.environ', {'OPENAI_API_KEY': 'unit-test-only', 'OPENAI_MODEL': 'mock-model'}):
            with patch('app.urlopen') as mocked:
                mocked.return_value.__enter__.return_value.read.return_value = json.dumps(reply).encode()
                result = self.agent.review_case('INV-182', 'live')
                payload = json.loads(mocked.call_args.args[0].data)
        self.assertEqual(payload['text']['format']['type'], 'json_schema')
        self.assertTrue(payload['text']['format']['strict'])
        self.assertFalse(payload['store'])
        self.assertEqual(result['engine'], 'live')
        self.assertEqual(result['model'], 'mock-model-v1')

    def test_live_unavailable_falls_back_without_secret_leak(self):
        with patch.dict('os.environ', {}, clear=True):
            result = self.agent.review_case('INV-182', 'live')
        self.assertEqual(result['validation']['status'], 'fallback')
        self.assertNotIn('Authorization', json.dumps(result))

    def test_env_loader_allows_only_app_settings_and_keeps_environment_override(self):
        env_path = Path(self.temp.name) / '.env'
        env_path.write_text('# local settings\nLLM_PROVIDER=openrouter\nOPENROUTER_API_KEY="test-secret"\nOPENROUTER_MODEL=openrouter/free\nPATH=untrusted\n', encoding='utf-8')
        with patch.dict('os.environ', {'OPENROUTER_MODEL': 'already-set'}, clear=True):
            load_env(env_path)
            import os
            self.assertEqual(os.environ['LLM_PROVIDER'], 'openrouter')
            self.assertEqual(os.environ['OPENROUTER_API_KEY'], 'test-secret')
            self.assertEqual(os.environ['OPENROUTER_MODEL'], 'already-set')
            self.assertNotIn('PATH', os.environ)

    def test_openrouter_free_adapter_and_secret_redaction(self):
        draft = self.agent.draft(self.agent.facts('INV-182'))
        reply = {'model': 'mock/free-provider', 'choices': [
            {'finish_reason': 'stop', 'message': {'content': json.dumps(draft)}}]}
        settings = {'LLM_PROVIDER': 'openrouter', 'OPENROUTER_API_KEY': 'unit-test-secret', 'OPENROUTER_MODEL': 'openrouter/free'}
        with patch.dict('os.environ', settings, clear=True), patch('app.urlopen') as mocked:
            mocked.return_value.__enter__.return_value.read.return_value = json.dumps(reply).encode()
            result = self.agent.review_case('INV-182', 'live')
            request = mocked.call_args.args[0]
            payload = json.loads(request.data)
            state = self.agent.state()
        self.assertEqual(request.full_url, 'https://openrouter.ai/api/v1/chat/completions')
        self.assertEqual(payload['model'], 'openrouter/free')
        self.assertEqual(payload['response_format']['type'], 'json_schema')
        self.assertEqual(result['engine'], 'live')
        self.assertEqual(result['model'], 'mock/free-provider')
        self.assertEqual(state['live_provider'], 'openrouter')
        self.assertTrue(state['live_available'])
        self.assertNotIn('unit-test-secret', json.dumps(result) + json.dumps(state) + json.dumps(self.store.audit()))

    def test_openrouter_truncated_response_falls_back(self):
        reply = {'model': 'mock/free-provider', 'choices': [
            {'finish_reason': 'length', 'message': {'content': '{}'}}]}
        with patch.dict('os.environ', {'LLM_PROVIDER': 'openrouter', 'OPENROUTER_API_KEY': 'test-only'}, clear=True):
            with patch('app.urlopen') as mocked:
                mocked.return_value.__enter__.return_value.read.return_value = json.dumps(reply).encode()
                result = self.agent.review_case('INV-182', 'live')
        self.assertEqual(result['validation']['status'], 'fallback')

    def test_live_interrupted_http_response_falls_back(self):
        with patch.dict('os.environ', {'LLM_PROVIDER': 'openrouter', 'OPENROUTER_API_KEY': 'test-only'}, clear=True):
            with patch('app.urlopen', side_effect=IncompleteRead(b'partial', 100)):
                result = self.agent.review_case('INV-182', 'live')
        self.assertEqual(result['validation']['status'], 'fallback')

    def test_secret_files_are_not_served_over_http(self):
        self.assertNotIn('OPENROUTER_API_KEY', json.dumps(self.agent.state()))

    def test_decisions_require_saved_review_and_cannot_clear_exceptions(self):
        with self.assertRaises(ValueError):
            self.agent.decide('unknown', 'hold', 'Demo reviewer', '')
        review = self.agent.review_case('INV-182')
        with self.assertRaises(ValueError):
            self.agent.decide(review['review_id'], 'mark_reviewed', 'Demo reviewer', '')
        with self.assertRaises(ValueError):
            self.agent.decide(review['review_id'], 'pay', 'Demo reviewer', '')
        decision = self.agent.decide(review['review_id'], 'hold', 'Demo reviewer', 'Request amended PO.')
        self.assertFalse(decision['payment_executed'])
        with self.assertRaises(ValueError):
            self.agent.decide(review['review_id'], 'escalate', 'Demo reviewer', '')
        clean = self.agent.review_case('INV-183')
        self.agent.decide(clean['review_id'], 'mark_reviewed', 'Demo reviewer', 'Evidence checked.')
        self.assertEqual(len(self.store.audit()['events']), 4)

    def test_old_review_cannot_accept_a_new_decision(self):
        old = self.agent.review_case('INV-183')
        self.agent.review_case('INV-183')
        with self.assertRaises(ValueError):
            self.agent.decide(old['review_id'], 'hold', 'Demo reviewer', 'Old tab.')

    def test_previous_human_decision_remains_visible_after_new_review(self):
        old = self.agent.review_case('INV-182')
        self.agent.decide(old['review_id'], 'hold', 'Demo reviewer', 'Need amended PO.')
        new = self.agent.review_case('INV-182')
        latest = self.store.latest_reviews()['INV-182']
        self.assertEqual(latest['review_id'], new['review_id'])
        self.assertIsNone(latest['decision'])
        self.assertEqual(latest['previous_decision']['decision'], 'hold')
        self.assertEqual(latest['previous_decision']['review_id'], old['review_id'])

    def test_audit_detects_materialized_record_changes_and_tail_deletion(self):
        review = self.agent.review_case('INV-182')
        self.agent.decide(review['review_id'], 'hold', 'Demo reviewer', '')
        self.assertTrue(self.store.audit()['records_consistent'])
        with self.store.connect() as conn:
            conn.execute('DROP TRIGGER decision_no_update')
            conn.execute("UPDATE decisions SET payload=replace(payload, 'hold', 'escalate')")
            conn.commit()
        self.assertTrue(self.store.audit()['chain_valid'])
        self.assertFalse(self.store.audit()['records_consistent'])
        with self.store.connect() as conn:
            conn.execute('DROP TRIGGER audit_no_delete')
            conn.execute('DELETE FROM audit_events WHERE sequence=(SELECT MAX(sequence) FROM audit_events)')
            conn.commit()
        self.assertFalse(self.store.audit()['records_consistent'])

    def test_audit_is_durable_chained_and_append_only(self):
        self.agent.review_case('INV-182')
        audit = Store(self.store.path).audit()
        self.assertTrue(audit['chain_valid'])
        self.assertEqual(len(audit['events']), 1)
        with self.store.connect() as conn:
            with self.assertRaises(Exception):
                conn.execute("UPDATE audit_events SET event_hash='changed'")
        event = audit['events'][0]
        self.assertEqual(event['details']['source_hash'], self.agent.facts('INV-182')['source_hash'])

    def test_concurrent_reviews_preserve_audit_chain(self):
        with ThreadPoolExecutor(max_workers=4) as pool:
            list(pool.map(lambda _: self.agent.review_case('INV-182'), range(8)))
        self.assertEqual(len(self.store.audit()['events']), 8)
        self.assertTrue(self.store.audit()['chain_valid'])


class HTTPTests(DemoFixture):
    def setUp(self):
        super().setUp()
        self.server = make_server(self.agent, 0)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        self.base = f'http://127.0.0.1:{self.server.server_port}'

    def request(self, path, data=None, origin=None, raw=None):
        headers = {'Content-Type': 'application/json'}
        if origin:
            headers['Origin'] = origin
        payload = json.dumps(data).encode() if data is not None else raw
        return urlopen(Request(self.base + path, payload, headers), timeout=5)

    def test_http_review_decision_export_and_no_payment_route(self):
        with self.request('/') as response:
            self.assertIn('Finance Exception Desk', response.read().decode())
        with self.request('/api/review', {'invoice_id': 'INV-182', 'mode': 'demo'}) as response:
            result = json.load(response)
        with self.request('/api/decision', {'review_id': result['review_id'], 'decision': 'hold',
                                            'actor': 'Demo reviewer', 'note': 'Verify PO.'}) as response:
            self.assertFalse(json.load(response)['payment_executed'])
        with self.request('/api/audit') as response:
            audit = json.load(response)
            self.assertTrue(audit['chain_valid'])
            self.assertEqual(len(audit['events']), 2)
        with self.request('/api/state') as response:
            state = json.load(response)
            self.assertEqual(state['summary']['payments_executed'], 0)
            self.assertEqual(state['cases'][0]['latest_review']['decision']['decision'], 'hold')
        with self.assertRaises(HTTPError) as error:
            self.request('/api/pay', {})
        self.assertEqual(error.exception.code, 404)

    def test_http_rejects_foreign_origin_unknown_id_and_bad_body(self):
        for data, origin, raw, status in [
            ({'invoice_id': 'INV-182'}, 'https://foreign.invalid', None, 403),
            ({'invoice_id': 'INV-UNKNOWN'}, None, None, 400),
            (None, None, b'{bad', 400),
            ([], None, None, 400),
        ]:
            with self.subTest(data=data, origin=origin), self.assertRaises(HTTPError) as error:
                self.request('/api/review', data, origin, raw)
            self.assertEqual(error.exception.code, status)

    def test_http_never_serves_environment_or_source_files(self):
        for path in ['/.env', '/.env.example', '/app.py', '/../.env']:
            with self.subTest(path=path), self.assertRaises(HTTPError) as error:
                self.request(path)
            self.assertEqual(error.exception.code, 404)

    def test_http_rejects_deeply_nested_json(self):
        with self.assertRaises(HTTPError) as error:
            self.request('/api/review', raw=('[' * 5000 + ']' * 5000).encode())
        self.assertEqual(error.exception.code, 400)


if __name__ == '__main__':
    unittest.main()
