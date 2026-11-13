import io,json,ssl,time,unittest,urllib.error,os,tempfile
from pathlib import Path
from unittest.mock import Mock
from gigachat_client import GigaChatClient,GigaChatError,AUTH_URL,API_URL,tls_context

class Response(io.BytesIO): pass

class ClientTests(unittest.TestCase):
    def client(self,responses):
        opener=Mock(); opener.open.side_effect=[Response(json.dumps(r).encode()) if not isinstance(r,Exception) else r for r in responses]
        return GigaChatClient('test-not-a-real-key',ssl.create_default_context(),opener=opener),opener
    def test_oauth_and_unicode_rewrite(self):
        c,o=self.client([{'access_token':'fake-token','expires_at':(time.time()+1800)*1000},{'choices':[{'finish_reason':'stop','message':{'content':'Контуры ровные.'}}]}])
        self.assertEqual(c.rewrite('Контуры обычные.','Улучши стиль'),'Контуры ровные.')
        auth=o.open.call_args_list[0].args[0]; request=o.open.call_args_list[1].args[0]
        self.assertEqual(auth.full_url,AUTH_URL); self.assertEqual(request.full_url,API_URL+'/chat/completions')
        self.assertEqual(request.get_header('Authorization'),'Bearer fake-token')
        self.assertIn('Контуры обычные.',json.loads(request.data)['messages'][1]['content'])
    def test_another_variant_includes_previous(self):
        c,o=self.client([{'access_token':'fake','expires_at':(time.time()+1800)*1000},{'choices':[{'finish_reason':'stop','message':{'content':'Новый вариант.'}}]}])
        c.rewrite('Исходник','Улучши',previous='Старый вариант')
        self.assertEqual(json.loads(o.open.call_args.args[0].data)['messages'][-2]['content'],'Старый вариант')
    def test_truncated_and_empty_response_rejected(self):
        for choice in [{'finish_reason':'length','message':{'content':'обрезан'}},{'finish_reason':'stop','message':{'content':''}}]:
            c,_=self.client([{'access_token':'fake','expires_at':(time.time()+1800)*1000},{'choices':[choice]}])
            with self.assertRaises(GigaChatError): c.rewrite('Текст','Редактируй')
    def test_error_does_not_echo_server_secret_or_report(self):
        error=urllib.error.HTTPError(AUTH_URL,401,'secret-echo',{},io.BytesIO(b'secret-echo'))
        c,_=self.client([error])
        with self.assertRaises(GigaChatError) as caught:c.models()
        self.assertNotIn('secret-echo',str(caught.exception)); self.assertIn('401',str(caught.exception))
    def test_tls_verification_enabled(self):
        context=tls_context(Path(__file__).parent/'gigachat_data')
        self.assertTrue(context.check_hostname); self.assertEqual(context.verify_mode,ssl.CERT_REQUIRED)
    @unittest.skipUnless(os.name=='nt','Windows DPAPI')
    def test_windows_encryption_roundtrip(self):
        from gigachat_secret import save_key,load_key
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'key'; save_key(path,'synthetic-secret')
            self.assertNotIn(b'synthetic-secret',path.read_bytes())
            self.assertEqual(load_key(path),'synthetic-secret')
