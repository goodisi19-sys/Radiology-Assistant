import json
import unittest
import urllib.error
import urllib.request
from yandex_editor import BrowserBridge


class BrowserBridgeTests(unittest.TestCase):
    def setUp(self):
        self.bridge = BrowserBridge('Контуры ровные. </textarea><script>not code</script>')
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    def tearDown(self): self.bridge.close()
    def post(self, text, origin=None):
        request = urllib.request.Request(self.bridge.origin + self.bridge.result_path,
            data=json.dumps({'text': text}).encode(), headers={'Content-Type': 'application/json',
            'Origin': self.bridge.origin if origin is None else origin})
        return self.opener.open(request, timeout=3)
    def test_local_page_escapes_report_and_requires_token(self):
        with self.opener.open(self.bridge.url, timeout=3) as result: body = result.read().decode()
        self.assertIn('&lt;/textarea&gt;', body)
        self.assertNotIn('<script>not code</script>', body)
        with self.assertRaises(urllib.error.HTTPError) as error:
            self.opener.open(self.bridge.origin + '/', timeout=3)
        self.assertEqual(error.exception.code, 404)
    def test_return_text_preserves_unicode(self):
        text = 'Контуры ровные; размеры 3.5 мм.\nT2 FLAIR.'
        with self.post(text) as result: self.assertEqual(result.status, 200)
        self.assertEqual(self.bridge.inbox.get(timeout=1), text)
    def test_external_origin_is_rejected(self):
        with self.assertRaises(urllib.error.HTTPError) as error:
            self.post('Do not accept', 'https://example.com')
        self.assertEqual(error.exception.code, 403)
        self.assertTrue(self.bridge.inbox.empty())
    def test_close_stops_server(self):
        self.bridge.close()
        self.assertFalse(self.bridge.thread.is_alive())
        with self.assertRaises(OSError): self.opener.open(self.bridge.url, timeout=1)

if __name__ == '__main__': unittest.main()
