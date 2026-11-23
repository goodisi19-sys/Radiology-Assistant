"""Category diagnostic on fixed synthetic queries; not clinical validation."""
import sys,json,tempfile,time
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT))
import app
from hybrid_worker import Encoder
from neural_retrieval import shortlist
QUERIES=[('нервная ткань внутри черепа','ГМ'),('полушария и желудочковая система','ГМ'),('селлярная область и гипофиз','ГМ'),('шейные позвонки и межпозвоночные диски','Позвоночник'),('поясничный отдел и корешки нервов','Позвоночник'),('дуральный мешок и позвоночный канал','Позвоночник'),('предстательная железа и семенные пузырьки','ОМТ'),('женские репродуктивные органы','ОМТ'),('матка и придатки','ОМТ'),('хрящ мениски и крестообразные связки','Суставы'),('вращательная манжета плеча','Суставы'),('суставная щель и поверхности бедренной кости','Суставы'),('желчевыводящие пути и печень','Брюшная полость'),('забрюшинное пространство почки','Брюшная полость'),('поджелудочная железа и селезенка','Брюшная полость'),('подкожная клетчатка и мышечные волокна','Мягкие ткани'),('локальная припухлость в толще мышцы','Мягкие ткани'),('просвет артерий и кровоток','Сосуды'),('венозные синусы','Сосуды'),('артериальное русло шеи','Сосуды')]
encoder=Encoder(ROOT/'models/rubert-tiny2');out=[]
with tempfile.TemporaryDirectory() as tmp,patch.object(app,'app_data_dir',return_value=Path(tmp)):
 lib=app.PhraseLibrary()
 corpus=lib.db.execute("SELECT t.id,t.title,t.category,COALESCE(l.content,t.content) FROM templates t LEFT JOIN template_layouts l ON l.template_id=t.id AND l.original_digest=raw_digest(t.content) WHERE COALESCE(l.kind,'')!='base-evidence'").fetchall()
 for query,gold in QUERIES:
  pool=shortlist(lib.ai,query,corpus);lex=lib.ai.search(query,corpus,limit=30)
  start=time.perf_counter();scores=encoder.rank(query,[' '.join(str(v) for v in row[1:])[:1000] for row in pool]);ms=(time.perf_counter()-start)*1000
  ranked=[row for score,row in sorted(zip(scores,pool),key=lambda p:-p[0]) if score>.45][:30]
  out.append({'query':query,'expected_category':gold,'shortlist_has_category':any(r[2]==gold for r in pool),'lexical_top_category':lex[0][2] if lex else None,'bert_top_category':ranked[0][2] if ranked else None,'lexical_top1':bool(lex and lex[0][2]==gold),'bert_top1':bool(ranked and ranked[0][2]==gold),'lexical_recall5':any(r[2]==gold for r in lex[:5]),'bert_recall5':any(r[2]==gold for r in ranked[:5]),'bert_ms':ms})
 lib.db.close()
result={'scope':'Manually specified synthetic paraphrases; real eligible library sources. Category match, not clinical template correctness. Not a statistically independent clinical validation. No training.','queries':out,'counts':{k:sum(r[k] for r in out) for k in ['shortlist_has_category','lexical_top1','bert_top1','lexical_recall5','bert_recall5']},'n':len(out)}
(ROOT/'reports/neural-retrieval-value.json').write_text(json.dumps(result,ensure_ascii=False,indent=2));print(json.dumps(result,ensure_ascii=False,indent=2))
