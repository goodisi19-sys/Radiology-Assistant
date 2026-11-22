"""Build-time teacher-forced candidate likelihood head, not free-form generation."""
from pathlib import Path
import urllib.request,json,hashlib,torch
from transformers import AutoTokenizer, AutoModelForSeq2SeqLM
from onnxruntime.quantization import quantize_dynamic,QuantType
rev='ed51b4a46603931380951a3d8456685c9215864f';source=Path('/workspace/work/hybrid-assets/sage');source.mkdir(parents=True,exist_ok=True)
for name in ['config.json','model.safetensors','tokenizer_config.json','tokenizer.json','special_tokens_map.json','added_tokens.json','vocab.json','merges.txt','README.md']:
 p=source/name
 if p.exists():continue
 try:urllib.request.urlretrieve(f'https://huggingface.co/ai-forever/sage-fredt5-distilled-95m/resolve/{rev}/{name}',p)
 except Exception:
  if name!='tokenizer.json':raise
model=AutoModelForSeq2SeqLM.from_pretrained(source,local_files_only=True).eval();tokenizer=AutoTokenizer.from_pretrained(source,local_files_only=True)
root=Path('models/sage');root.mkdir(parents=True,exist_ok=True);tokenizer.backend_tokenizer.save(str(root/'tokenizer.json'))
class Scorer(torch.nn.Module):
 def __init__(self):super().__init__();self.model=model
 def forward(self,input_ids,attention_mask,decoder_input_ids,labels):
  logits=self.model(input_ids=input_ids,attention_mask=attention_mask,decoder_input_ids=decoder_input_ids,use_cache=False).logits
  logp=torch.nn.functional.log_softmax(logits,dim=-1)
  values=logp.gather(2,labels.unsqueeze(-1)).squeeze(-1);mask=labels.ne(model.config.pad_token_id).to(values.dtype)
  return (values*mask).sum(dim=1)/mask.sum(dim=1).clamp(min=1)
sample=tokenizer('Срединные структуры не смещены.',return_tensors='pt');labels=sample['input_ids'];decoder=model._shift_right(labels)
raw=source/'scorer.onnx'
torch.onnx.export(Scorer().eval(),(sample['input_ids'],sample['attention_mask'],decoder,labels),str(raw),input_names=['input_ids','attention_mask','decoder_input_ids','labels'],output_names=['score'],dynamic_axes={k:{0:'batch',1:'source' if k in ['input_ids','attention_mask'] else 'target'} for k in ['input_ids','attention_mask','decoder_input_ids','labels']}|{'score':{0:'batch'}},opset_version=17,dynamo=False)
quantize_dynamic(str(raw),str(root/'scorer.int8.onnx'),weight_type=QuantType.QInt8)
(root/'config.json').write_text(json.dumps({'pad_token_id':model.config.pad_token_id,'decoder_start_token_id':model.config.decoder_start_token_id,'revision':rev,'license':'MIT'}))
(root/'README.md').write_bytes((source/'README.md').read_bytes())
(root/'ORIGIN.json').write_text(json.dumps({'repo':'ai-forever/sage-fredt5-distilled-95m','revision':rev,'license':'MIT','export':'torch2.6.0 ONNX17 ORT1.23.2 INT8 teacher-forced mean log likelihood'},indent=2))
print('SAGE',[(p.name,p.stat().st_size) for p in root.iterdir()],flush=True)
