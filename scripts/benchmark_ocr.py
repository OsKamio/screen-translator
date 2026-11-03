import gc, json, statistics, sys, time
from pathlib import Path
import numpy as np
from PIL import Image,ImageFont,ImageDraw
from rapidocr_onnxruntime import RapidOCR
profiles=[('original',{}),('threads2',dict(intra_op_num_threads=2,inter_op_num_threads=1)),('max1280_threads2',dict(intra_op_num_threads=2,inter_op_num_threads=1,det_limit_type='max',det_limit_side_len=1280))]
cases=[]
for name,w,h,size,lines in [
 ('subtitle',1152,155,26,['Please open the settings window and click Save.','实时翻译应该清晰流畅，窗口保持稳定。']),
 ('small_text',900,220,16,['Small text should remain readable after optimization.','小字号文字也需要准确识别，不能牺牲清晰度。']),
 ('document',1000,760,23,['The quick brown fox jumps over the lazy dog.','这是中文识别准确率检查。']*5)]:
 im=Image.new('RGB',(w,h),'white');d=ImageDraw.Draw(im);f=ImageFont.truetype(r'C:\Windows\Fonts\msyh.ttc',size)
 for i,line in enumerate(lines): d.text((12,8+i*(size+16)),line,font=f,fill='black')
 cases.append((name,np.asarray(im)[:,:,::-1].copy(),lines))
rows=[]
for profile,kw in profiles:
 start=time.perf_counter();engine=RapidOCR(**kw);init=time.perf_counter()-start
 engine(np.zeros((40,120,3),np.uint8))
 for name,im,expected in cases:
  costs=[];result=None
  for _ in range(3):
   start=time.perf_counter();result,_=engine(im);costs.append(round((time.perf_counter()-start)*1000,2))
  text='\n'.join(r[1] for r in (result or [])); row=dict(profile=profile,case=name,init_s=round(init,2),median_ms=statistics.median(costs),samples_ms=costs,text=text,expected=expected)
  rows.append(row);print(json.dumps(row,ensure_ascii=True),flush=True)
 del engine;gc.collect()
Path(sys.argv[1]).write_text(json.dumps(rows,ensure_ascii=False,indent=2),encoding='utf-8')
