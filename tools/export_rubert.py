"""Build-time only. Export pinned MIT RuBERT encoders to dynamic INT8 ONNX."""
import json, urllib.request, hashlib
from pathlib import Path
import torch
from transformers import AutoModel
from onnxruntime.quantization import quantize_dynamic, QuantType

REVISIONS={'rubert-tiny2':'e8ed3b0c8bbf4fb6984c3de043bf7d2f4e5969ae','rubert-tiny':'5441c5ea8026d4f6d7505ec004845409f1259fb1'}
for name,rev in REVISIONS.items():
    root=Path('models')/name;root.mkdir(parents=True,exist_ok=True)
    source=Path('/workspace/work/hybrid-assets')/name;source.mkdir(parents=True,exist_ok=True)
    for file in ('config.json','model.safetensors','tokenizer.json','tokenizer_config.json','special_tokens_map.json','vocab.txt','README.md'):
        target=source/file
        if not target.exists():urllib.request.urlretrieve(f'https://huggingface.co/cointegrated/{name}/resolve/{rev}/{file}',target)
    class Encoder(torch.nn.Module):
        def __init__(self):
            super().__init__();self.model=AutoModel.from_pretrained(source,local_files_only=True).eval()
        def forward(self,input_ids,attention_mask,token_type_ids):
            v=self.model(input_ids=input_ids,attention_mask=attention_mask,token_type_ids=token_type_ids).last_hidden_state[:,0]
            return torch.nn.functional.normalize(v,p=2,dim=1)
    model=Encoder().eval();dummy=torch.ones((1,12),dtype=torch.int64)
    raw=source/'float.onnx'
    torch.onnx.export(model,(dummy,dummy,dummy*0),str(raw),input_names=['input_ids','attention_mask','token_type_ids'],output_names=['embedding'],dynamic_axes={k:{0:'batch',1:'sequence'} for k in ['input_ids','attention_mask','token_type_ids']}|{'embedding':{0:'batch'}},opset_version=17,dynamo=False)
    quantize_dynamic(str(raw),str(root/'model.int8.onnx'),weight_type=QuantType.QInt8)
    for file in ['tokenizer.json','config.json','README.md']:(root/file).write_bytes((source/file).read_bytes())
    (root/'ORIGIN.json').write_text(json.dumps({'repo':'cointegrated/'+name,'revision':rev,'license':'MIT','export':'torch2.6.0 ONNX opset17 CLS L2 INT8 ORT1.23.2'},indent=2))
    print(name,(root/'model.int8.onnx').stat().st_size,hashlib.sha256((root/'model.int8.onnx').read_bytes()).hexdigest(),flush=True)
