"""Run source kernel stages with full-payload checkpoints and private outputs."""

from .console import say

import hashlib
import fcntl
import shutil
import tempfile
from pathlib import Path

from .core import digest_file, load_json, publish_directory, require, save_json
from .kernel import prepare_research_input, prepare_bootstrap_donor
from . import kernel_base
from . import kernel_chestnut, kernel_ch2, kernel_d2333, kernel_ag1, kernel_transplant, kernel_vmca, kernel_aop
from . import kernel_maggie, kernel_ak1, kernel_ak2
from . import kernel_battery, kernel_microphone
from . import kernel_panic, kernel_mc2
from . import kernel_uart
from . import kernel_uart_fixes, kernel_homer_consumer
from . import kernel_home_records
from .kc import KC
from .kernel_image import package


def rebuild(project, through='HC3', *, fresh=False):
    project.initialize()
    with (project.work / 'kernel-build.lock').open('a+') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            require(False, 'Another kernel build is already running for this project. Wait for it to finish.')
        if fresh:
            from .core import Project
            folder = Path(tempfile.mkdtemp(prefix='kernel-fresh-', dir=project.work))
            (folder / 'extracted').symlink_to(project.work / 'extracted', target_is_directory=True)
            isolated = Project(project.root)
            isolated.work = folder
            raw = _rebuild(isolated, through)
            if through == 'HC3':
                project.record('kernel', isolated.stage('kernel'))
                project.record('kernel-clean-validation', {'workspace': str(folder), 'raw_sha256': digest_file(raw, ('sha256',))['sha256'],
                               'all_stages_rebuilt': True, 'prior_kernel_cache_used': False})
            return raw
        return _rebuild(project, through)


def _rebuild(project, through):
    require(__debug__, 'Kernel reconstruction requires Python assertions; do not use python -O.')
    project.initialize()
    lock = load_json(project.root / 'profiles/kernel-stages.json')
    stages = lock['stages']
    require(through in {s['id'] for s in stages}, f'Unknown kernel stage {through}.')
    prepare_research_input(project, 'ipad_target')
    source = project.work / 'kernel-inputs/ipad_target/kernel.research.raw'
    target = project.work / 'kernel-chain'
    target.mkdir(parents=True, exist_ok=True)
    completed = []
    for stage in stages:
        actual = digest_file(source, ('sha256',))['sha256']
        require(actual == stage['input_raw_sha256'], f"Kernel input checkpoint failed before {stage['id']}.")
        destination = target / stage['name']
        output = destination / 'kernelcache.raw'
        if destination.exists():
            receipt = load_json(destination / 'receipt.json')
            require(receipt['input_raw_sha256'] == actual and
                    digest_file(output, ('sha256',))['sha256'] == stage['output_raw_sha256'],
                    f"Cached kernel checkpoint changed: {stage['id']}")
            say(f"VERIFIED cached kernel checkpoint: {stage['id']}", 'success')
        else:
            require(stage['id'] in {*kernel_base.FUNCTIONS, 'I', 'CH1', 'CH2', 'DS2', 'AG1', 'AU3', 'AU4', 'AU5', 'AU6', 'MG1', 'AK1', 'AK2', 'BT1', 'MC1', 'MC1D', 'MC2D', 'HU9', 'HU10', 'HU11', 'HU12', 'HC1', 'HC3'},
                    f"Stage {stage['id']} is not ported yet. Earlier verified checkpoints are preserved; no final kernel was published.")
            staging = Path(tempfile.mkdtemp(prefix='.' + stage['id'] + '-', dir=target))
            try:
                if stage['id'] == 'CH1':
                    prepare_research_input(project, 'iphone8_donor')
                    donor = project.work / 'kernel-inputs/iphone8_donor/kernel.research.raw'
                    data, edits = kernel_chestnut.apply(source, donor, staging)
                elif stage['id'] == 'CH2':
                    data, edits = kernel_ch2.apply(source, project, staging)
                elif stage['id'] == 'DS2':
                    prepare_bootstrap_donor(project)
                    donor = project.work / 'kernel-inputs/iphone7_bootstrap/kernel.sshrd.raw'
                    data, edits = kernel_d2333.apply(source, donor, project.root / 'profiles/d2333-bindings.json', staging)
                elif stage['id'] == 'AG1':
                    data, edits = kernel_ag1.apply(source, project, staging)
                elif stage['id'] == 'AU3':
                    prepare_research_input(project, 'iphone8_donor')
                    donor = project.work / 'kernel-inputs/iphone8_donor/kernel.research.raw'
                    data, edits = kernel_transplant.apply(source, donor, staging,
                        'com.apple.driver.AppleOrion', 'com.apple.driver.AppleCS35L26Amp', b'\x1b[33mAG1:%.128s\x1b[0m\n\0')
                elif stage['id'] == 'AU4':
                    prepare_bootstrap_donor(project)
                    donor = project.work / 'kernel-inputs/iphone7_bootstrap/kernel.sshrd.raw'
                    bindings, review = kernel_vmca.bind(KC(donor), KC(source), project.root / 'profiles/virtualmca-bindings.json')
                    data, edits = kernel_transplant.apply(source, donor, staging,
                        'com.apple.driver.AppleDPDisplay', 'com.apple.driver.AppleVirtualMCA',
                        b'\x1b[35mAU3:%.128s\x1b[0m\n\0', b'\x1b[35mAU4:%.128s\x1b[0m\n\0',
                        private_bindings=bindings, private_review=review)
                elif stage['id'] == 'AU5':
                    data, edits = kernel_aop.apply(source, project, staging)
                elif stage['id'] == 'AU6':
                    prepare_research_input(project, 'iphone8_donor')
                    donor = project.work / 'kernel-inputs/iphone8_donor/kernel.research.raw'
                    data, edits = kernel_transplant.apply(source, donor, staging,
                        'com.apple.driver.AppleCS42L83Audio', 'com.apple.driver.AppleAD81006',
                        b'\x1b[35mAU4:%.128s\x1b[0m\n\0', b'\x1b[35mAU6:%.128s\x1b[0m\n\0')
                elif stage['id'] == 'MG1':
                    prepare_bootstrap_donor(project)
                    donor = project.work / 'kernel-inputs/iphone7_bootstrap/kernel.sshrd.raw'
                    private, review, slots, extra, patches, finish = kernel_maggie.prepare(KC(donor), KC(source), project.root / 'profiles/maggie-abi.json')
                    data, edits = kernel_transplant.apply(source, donor, staging,
                        kernel_maggie.OLD, kernel_maggie.NAME, b'\x1b[35mAU6:%.128s\x1b[0m\n\0', b'\x1b[35mMG1:%.128s\x1b[0m\n\0',
                        private_bindings=private, private_review=review, slot_overrides=slots,
                        extra_donor_slots=extra, donor_word_patches=patches, finalize=finish,
                        non_instruction_words={0xfffffff0059f4bf8: {'bytes': '887d16946d80b93f', 'reason': 'Reviewed Libm F64 literal'}})
                elif stage['id'] in {'AK1', 'AK2'}:
                    data, edits = (kernel_ak1 if stage['id'] == 'AK1' else kernel_ak2).apply(source, staging)
                elif stage['id'] == 'BT1':
                    prepare_bootstrap_donor(project)
                    donor = project.work / 'kernel-inputs/iphone7_bootstrap/kernel.sshrd.raw'
                    private, review = kernel_battery.prepare(KC(donor), KC(source), project.root / 'profiles/d2333-bindings.json', project.root / 'profiles/battery-bindings.json')
                    def tag(entry):
                        entry['IOKitPersonalities']['Tigris']['BT1-PortSource'] = 'D10 iOS15.6 SN2400, native16 dependencies'
                    data, edits = kernel_transplant.apply(source, donor, staging,
                        'com.apple.driver.AppleUSBCardReader', kernel_battery.NAME,
                        b'\x1b[35mMG1:%.128s\x1b[0m\n\0', b'\x1b[32mBT1:%.128s\x1b[0m\n\0',
                        private_bindings=private, private_review=review, entry_transform=tag)
                elif stage['id'] == 'MC1':
                    prepare_bootstrap_donor(project)
                    donor = project.work / 'kernel-inputs/iphone7_bootstrap/kernel.sshrd.raw'
                    private, review, slots, patches, extra, skip, finish = kernel_microphone.prepare(KC(donor), KC(source), project.root / 'profiles/microphone-abi.json')
                    data, edits = kernel_transplant.apply(source, donor, staging,
                        kernel_microphone.OLD, kernel_microphone.NAME, b'\x1b[32mBT1:%.128s\x1b[0m\n\0', b'\x1b[33mMC1:%.128s\x1b[0m\n\0',
                        private_bindings=private, private_review=review, slot_overrides=slots, donor_word_patches=patches,
                        finalize=finish, extra_donor_slots=extra, skip_donor_slots=skip, expanded_segments={'__DATA_CONST': 0x6000+32+285*8},
                        non_instruction_words={0xfffffff0059f4bf8: {'bytes': '887d16946d80b93f', 'reason': 'Reviewed Libm F64 literal'}})
                elif stage['id'] == 'MC1D':
                    battery = target / 'BT1_AK2_SN2400_battery/kernelcache.raw'
                    data, edits = kernel_panic.apply(source, battery, project, staging)
                elif stage['id'] == 'MC2D':
                    prepare_bootstrap_donor(project)
                    donor = project.work / 'kernel-inputs/iphone7_bootstrap/kernel.sshrd.raw'
                    data, edits = kernel_mc2.apply(source, donor, project, staging)
                elif stage['id'] == 'HU9':
                    prepare_bootstrap_donor(project)
                    donor = project.work / 'kernel-inputs/iphone7_bootstrap/kernel.sshrd.raw'
                    data, edits = kernel_uart.apply(source, donor, project, staging)
                elif stage['id'] in {'HU10', 'HU11'}:
                    donor = project.work / 'kernel-inputs/iphone7_bootstrap/kernel.sshrd.raw'
                    meta = load_json(target / 'HU9_MC2D_UART_ABI_trace/receipt.json')['edits']
                    function = kernel_uart_fixes.hu10 if stage['id'] == 'HU10' else kernel_uart_fixes.hu11
                    data, edits = function(source, donor, meta)
                elif stage['id'] == 'HU12':
                    data, edits = kernel_uart_fixes.hu12(source, project.root / 'profiles/homer-management.json')
                elif stage['id'] == 'HC1':
                    donor = project.work / 'kernel-inputs/iphone7_bootstrap/kernel.sshrd.raw'
                    data, edits = kernel_homer_consumer.apply(source, donor, project, staging)
                elif stage['id'] == 'HC3':
                    original = target / 'HU12_management_dispatch/kernelcache.raw'
                    data, edits = kernel_home_records.apply(source, original, project, staging)
                else:
                    data, edits = kernel_base.apply(stage['id'], source, project, staging)
                result = hashlib.sha256(data).hexdigest()
                if result != stage['output_raw_sha256']:
                    failure = project.work / 'kernel-failures' / stage['id']
                    failure.mkdir(parents=True, exist_ok=True)
                    (failure / 'kernelcache.raw').write_bytes(data)
                    save_json(failure / 'comparison.json', {'expected': stage['output_raw_sha256'], 'actual': result})
                require(result == stage['output_raw_sha256'], f"Full kernel output differs at stage {stage['id']}; refusing this checkpoint.")
                raw = staging / 'kernelcache.raw'
                raw.write_bytes(data)
                before, after = KC(source), KC(raw)
                require(before.segments == after.segments and (stage['id'] in {'CH1', 'DS2', 'AU3', 'AU4', 'AU6', 'MG1', 'BT1', 'MC1', 'HU9', 'HU10', 'HC1'} or before.xml == after.xml),
                        f"Unexpected base-stage Mach-O or prelink change: {stage['id']}")
                receipt = {**stage, 'edits': edits, 'full_raw_hash_match': True,
                           'unchanged_outer_layout': True, 'prelink_changed': before.xml != after.xml}
                save_json(staging / 'receipt.json', receipt)
                publish_directory(staging, destination)
                say(f"BUILT kernel checkpoint: {stage['id']} / full payload matches the historical artifact", 'success')
            except BaseException:
                shutil.rmtree(staging, ignore_errors=True)
                raise
        completed.append(stage['id'])
        source = output
        project.record('kernel-chain', {'completed': completed, 'last_stage': stage['id'],
                       'last_raw': str(output), 'last_raw_sha256': stage['output_raw_sha256'],
                       'clean_rebuild_complete': stage['id'] == 'HC3'})
        if stage['id'] == through:
            if through == 'HC3':
                package(project, output)
            return output
    raise RuntimeError('Kernel stage traversal did not reach its requested target.')
