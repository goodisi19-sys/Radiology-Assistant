"""CI-only synthetic probe of the separately frozen CPU worker."""
import json,subprocess,sys
from pathlib import Path
root=Path(sys.argv[1]).resolve();helper=root/'RadiologyNeuralWorker'/'RadiologyNeuralWorker.exe'
task={'root':str(root/'models'/'rubert-tiny2'),'context':'Контуры ровные.','options':['Контуры ровные.','Коленный сустав.'],'threads':1,'diagnostic':True}
p=subprocess.run([str(helper)],input=json.dumps(task)+'\n',encoding='utf8',text=True,capture_output=True,timeout=30)
print('Compiled worker return code:',p.returncode);print(p.stdout);print(p.stderr)
obj=json.loads(p.stdout.splitlines()[0]);assert 'scores' in obj,obj
