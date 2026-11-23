"""Copy installed dependency notices verbatim into the portable distribution."""
from importlib import metadata
from pathlib import Path
import shutil,sys

root=Path('package')/'THIRD_PARTY';root.mkdir(parents=True,exist_ok=True)
lines=['Dependency notices. Hybrid runtime dependencies; model notices are in models/.']
for name in ('PySide6','PySide6-Essentials','PySide6-Addons','shiboken6','rapidfuzz','spylls','python-docx','lxml','brotli','pyinstaller','onnxruntime','tokenizers','psutil','numpy'):
    dist=metadata.distribution(name);lines.append(f'{dist.metadata["Name"]} {dist.version}')
    for file in dist.files or []:
        p=Path(str(file));base=p.name.upper()
        if not (base.startswith(('LICENSE','COPYING','NOTICE')) or 'licenses' in {x.lower() for x in p.parts}):continue
        source=Path(dist.locate_file(file))
        if not source.is_file():continue
        relative=Path(*[part for part in p.parts if part not in ('..','.')])
        destination=root/name/relative;destination.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(source,destination)
python_license=Path(sys.base_prefix)/'LICENSE.txt'
if python_license.exists():shutil.copy2(python_license,root/'CPython-LICENSE.txt')
(root/'DEPENDENCIES.txt').write_text('\n'.join(lines)+'\n\nQt/PySide6: LGPLv3/GPLv3 or commercial terms; bundled dynamic Qt libraries retain upstream licenses.\nRapidFuzz and Spylls: MIT. Russian Hunspell dictionary: see the separately bundled BSD-style notice.\nPyInstaller bootloader: GPL with its distribution exception.\nBundled RuBERT-tiny/tiny2 and SAGE INT8 weights: MIT; original model cards and revisions are in models/.\nONNX Runtime: MIT; tokenizers: Apache-2.0; psutil and NumPy: BSD notices included.\nLocal inference does not call external model APIs. Google review uses the installed default browser after explicit preview; long prompts are copied to the clipboard.\n',encoding='utf8')
