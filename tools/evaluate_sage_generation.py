"""Optional developer-only INT8 greedy decoder experiment. Not part of application runtime."""
import argparse,json,time,re
from pathlib import Path

def aligned_change(source,result):
 from hybrid_safety import safe_pair
 a=list(re.finditer(r'\w+',source));b=list(re.finditer(r'\w+',result))
 if len(a)!=len(b):return None
 changes=[(x,y) for x,y in zip(a,b) if x.group()!=y.group()]
 if len(changes)!=1:return None
 x,y=changes[0];candidate=source[:x.start()]+y.group()+source[x.end():]
 if candidate!=result or not safe_pair(source,candidate):return None
 return (x.start(),x.end(),y.group())

def run(source,output):
 import torch,numpy as np,onnxruntime as ort
 from transformers import AutoTokenizer,AutoModelForSeq2SeqLM
 from onnxruntime.quantization import quantize_dynamic,QuantType
 torch.set_num_threads(2);tokenizer=AutoTokenizer.from_pretrained(source,local_files_only=True)
 model=AutoModelForSeq2SeqLM.from_pretrained(source,local_files_only=True).eval()
 class Logits(torch.nn.Module):
  def forward(self,input_ids,attention_mask,decoder_input_ids):return model(input_ids=input_ids,attention_mask=attention_mask,decoder_input_ids=decoder_input_ids,use_cache=False).logits
 wrapper=Logits();wrapper.model=model
 raw=output/'decoder.onnx';quant=output/'decoder.int8.onnx';output.mkdir(parents=True,exist_ok=True)
 if not quant.exists():
  batch=tokenizer('Срединные струткуры не смещены.',return_tensors='pt');decoder=torch.tensor([[model.config.decoder_start_token_id]])
  torch.onnx.export(wrapper,(batch['input_ids'],batch['attention_mask'],decoder),str(raw),input_names=['input_ids','attention_mask','decoder_input_ids'],output_names=['logits'],dynamic_axes={'input_ids':{0:'batch',1:'source'},'attention_mask':{0:'batch',1:'source'},'decoder_input_ids':{0:'batch',1:'target'},'logits':{0:'batch',1:'target'}},opset_version=17,dynamo=False)
  quantize_dynamic(str(raw),str(quant),weight_type=QuantType.QInt8)
 opts=ort.SessionOptions();opts.intra_op_num_threads=2;opts.inter_op_num_threads=1;opts.log_severity_level=3
 session=ort.InferenceSession(str(quant),sess_options=opts,providers=['CPUExecutionProvider']);cases=[('Срединные струткуры не смещены.','Срединные структуры не смещены.'),('Срединные структуры не смещны.','Срединные структуры не смещены.'),('Контруы ровные.','Контуры ровные.'),('Правой почки киста 10 мм.','Правой почки киста 10 мм.')];rows=[]
 for text,gold in cases:
  batch=tokenizer(text,return_tensors='np');decoder=np.array([[model.config.decoder_start_token_id]],dtype=np.int64);start=time.perf_counter()
  for _ in range(16):
   logits=session.run(None,{'input_ids':batch['input_ids'],'attention_mask':batch['attention_mask'],'decoder_input_ids':decoder})[0];token=int(logits[0,-1].argmax());decoder=np.concatenate([decoder,np.array([[token]],dtype=np.int64)],axis=1)
   if token==model.config.eos_token_id:break
  result=tokenizer.decode(decoder[0],skip_special_tokens=True);change=aligned_change(text,result)
  rows.append({'input':text,'result':result,'gold':gold,'exact':result==gold,'safe_aligned_single_word':bool(change),'ms':(time.perf_counter()-start)*1000})
 report={'experimental':True,'int8':True,'max_new_tokens':16,'cases':rows,'model_bytes':quant.stat().st_size,'ship_decoder':False,'reason':'Tiny synthetic probe does not establish independent clinical benefit. Keep bounded candidate scorer; do not ship extra decoder.'}
 Path('reports/sage-decoder-experiment.json').write_text(json.dumps(report,ensure_ascii=False,indent=2));print(json.dumps(report,ensure_ascii=False))
if __name__=='__main__':
 parser=argparse.ArgumentParser();parser.add_argument('source',type=Path);parser.add_argument('output',type=Path);args=parser.parse_args();run(args.source,args.output)
