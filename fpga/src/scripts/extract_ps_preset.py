"""Extract only the PS7 properties from the pinned official PYNQ-Z2 design."""
from pathlib import Path
import hashlib
import json
import re
root = Path(__file__).resolve().parents[1]
source = root/'vendor'/'pynq_z2_base.tcl'
text = source.read_text()
start = text.index('# Create instance: ps7_0, and set properties')
block = text[start:text.index('] $ps7_0', start)]
properties = re.findall(r'(CONFIG\.PCW_\w+)\s+\{([^}]*)\}', block)
assert len(properties)>400
out = '# PS settings extracted from Xilinx/PYNQ boards/Pynq-Z2/base/base.tcl.\n'
out += 'set_property -dict [list \\\n'
out += ''.join(f'    {key} {{{value}}} \\\n' for key,value in properties)
out += '] [get_bd_cells ps7_0]\n'
(root/'scripts'/'ps7_preset.tcl').write_text(out)
(root/'vendor'/'provenance.json').write_text(json.dumps({
    'source_url':'https://raw.githubusercontent.com/Xilinx/PYNQ/master/boards/Pynq-Z2/base/base.tcl',
    'download_date':'2026-09-22', 'source_sha256':hashlib.sha256(source.read_bytes()).hexdigest(),
    'properties':len(properties)},indent=2))
print('PS7 properties:',len(properties))
