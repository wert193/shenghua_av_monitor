"""Reject the known auxiliary-reset wiring error before loading PL."""
import xml.etree.ElementTree as ET

def check_reset(path):
    tree = ET.parse(path)
    module = next(m for m in tree.iter('MODULE') if m.get('INSTANCE') == 'reset_0')
    params = {p.get('NAME'): p.get('VALUE') for p in module.iter('PARAMETER')}
    ports = {p.get('NAME'): p for p in module.iter('PORT')}
    if params.get('C_EXT_RESET_HIGH') != '0' or params.get('C_AUX_RESET_HIGH') != '1':
        raise ValueError('Unsafe reset polarity: refusing to load this FPGA package')
    if ports['aux_reset_in'].get('SIGNAME') != 'zero_dout':
        raise ValueError('Unexpected auxiliary reset wiring')
    return True
