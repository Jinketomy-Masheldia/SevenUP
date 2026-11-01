"""Compile the normal-display PMU empty-sample guard from source."""

from .core import require
from .kernel_base import Edits, branch
from .kernel_compile import assembly


def apply(source, project, work):
    edits = Edits(source)
    k, cave, hook = edits.k, 0xfffffff0078bb840, 0xfffffff005c976d8
    require(k.read(hook, 12).hex() == 'f80300aa080040f9081140f9', 'PMU fault context changed.')
    require(k.read(0xfffffff005c977c8, 24).hex() == '680240f9081540f9e00313aa00013fd6130080d2e00313aa', 'PMU native cleanup changed.')
    flat, symbols, base = assembly(project, project.root / 'resources/kernel/ag1_pmu_sample_guard.s', work, '_ag_entry')
    addresses = {name: cave + address - base for name, address in symbols.items() if base <= address < base + len(flat)}
    for name, destination in [('_ag_resume', 0xfffffff005c976dc), ('_ag_fail', 0xfffffff005c977c8), ('_ag_printf', 0xfffffff007215444)]:
        offset = addresses[name] - cave
        require(flat[offset:offset+4] == branch(addresses[name], addresses[name]), 'AG1 import placeholder changed.')
        flat[offset:offset+4] = branch(addresses[name], destination)
    require(len(flat) == 173 and cave + len(flat) <= 0xfffffff0078bc000, 'AG1 helper allocation changed.')
    edits.put(hook, k.read(hook, 4), branch(hook, cave), 'Guard only a NULL first sample before native access')
    edits.put(cave, bytes(len(flat)), flat, 'Compiled PMU guard, preserving native success and cleanup paths')
    edits.string(b'\x1b[36mDS2:%.128s\x1b[0m\n', b'\x1b[33mAG1:%.128s\x1b[0m\n')
    require(k.read(0xfffffff0078bb400, 476) == bytes(476) and k.read(0xfffffff0078bb600, 520) == bytes(520),
            'Unexpected historical DS2 display diagnostic helpers are present.')
    (work / 'guard.flat').write_bytes(flat)
    return bytes(edits.output), {'edits': edits.records, 'normal_display_handoff_preserved': True, 'helper_size': len(flat)}
