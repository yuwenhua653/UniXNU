#!/usr/bin/env python3
"""Compile the native A840 stage with the prepared kernel's real C/C++ recipes.

No SDK stand-ins, foreign iPad bindings or synthetic firmware are accepted.
This stage does not yet build/advertise a Metal accelerator or runtime addon.
"""
import hashlib
import json
from pathlib import Path
import subprocess
from prepare_sources import stage

CPP = ('NativeAdrenoCpu', 'NativeAdrenoMemory', 'NativeAdrenoSmmuMemory', 'NativeAdrenoSmmuContext',
       'NativeAdrenoVm', 'NativeAdrenoGmuMemory', 'NativeAdrenoGmuContext', 'NativeAdrenoGpuContext',
       'NativeAdrenoRing', 'NativeAdrenoCpInit', 'NativeAdrenoIrq', 'NativeAdrenoTimer',
       'NativeAdrenoSubmit', 'NativeAdrenoUserClient', 'NativeAdrenoPublish')


def require(ok, why):
    if not ok:
        raise ValueError(why)


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def firmware_inputs(source, firmware):
    pins = json.loads((source/'firmware-3.0.306.json').read_text())['files']
    for name, row in pins.items():
        path = firmware/name
        require(path.is_file() and path.stat().st_size == row['bytes'] and sha(path) == row['sha256'],
                'Missing or mismatched myron 3.0.306 GPU firmware: '+name)
    return pins


def compile_gpu(tree, here, out, builder, target, env, record):
    from build_ufs_dormant import macho, initializers
    from display_build import iphone_target_flags, check_object_imports
    source = here/'gpu'
    out.mkdir(parents=True, exist_ok=True)
    require(env.get('MYRON_GPU_NATIVE') == '1', 'GPU native compilation must be explicitly selected')
    require(env.get('MYRON_GPU_FIRMWARE'), 'MYRON_GPU_FIRMWARE must name the verified local input directory')
    firmware = Path(env['MYRON_GPU_FIRMWARE']).resolve()
    pins = firmware_inputs(source, firmware)
    report = dict(hardware_tested=False, metal_enabled=False, gpu_scanout_enabled=False,
                  runtime_opt_in='myron-gpu=1', interrupt_mode='real-fence polling, GPU interrupt mask zero',
                  firmware=pins, dependencies=stage(here.parents[1]/'references/myron-gpu', out/'source'))
    recipe = tree/'build/xnu/ios-obj/DEVELOPMENT_ARM64_BCM2837/osfmk/DEVELOPMENT/startup.o.json'
    c_record = json.loads(recipe.read_text().strip().rstrip(','))
    objcopy = Path(subprocess.check_output(['brew', '--prefix', 'llvm'], text=True).strip())/'bin/llvm-objcopy'
    includes = [x for p in (source, tree/'.cache/xnu-work/osfmk',
                           *(out/'source'/k for k in ('NativeAdreno', 'ArmSmmu4K', 'AdrenoFirmware', 'AdrenoPM4')))
                for x in ('-I', str(p))]
    sources = [out/'source/NativeAdreno'/(n+'.cpp') for n in CPP]
    sources += [source/'MyronGpuService.cpp', source/'MyronGpuBoundary.cpp']
    sources += [source/(n+'.c') for n in ('MyronGmu', 'MyronCmdDb', 'MyronHfi')]
    sources += [out/'source/AdrenoFirmware/AdrenoHfi.c', out/'source/AdrenoPM4/AdrenoPM4.c']
    sources += sorted((out/'source/ArmSmmu4K').glob('ArmSmmu4K*.c'))
    objects, evidence, late_symbols = [], [], []

    def compile_one(src):
        obj = out/(src.stem+'.o')
        rec = c_record if src.suffix == '.c' else record
        cmd = builder.compile_command(rec, src, obj, includes, ['-Wno-overloaded-virtual'])
        with (out/(src.stem+'-compile.log')).open('w') as log:
            status = subprocess.run(cmd, cwd=rec['directory'], env=env, stdout=log, stderr=subprocess.STDOUT)
        require(not status.returncode, (out/(src.stem+'-compile.log')).read_text()[-8000:])
        target.check_object(obj.read_bytes(), src.name)
        info = macho(obj.read_bytes(), 1)
        check_object_imports(info)
        init = initializers(info)
        if init:
            symbol = '__GLOBAL__sub_I_'+src.name
            require(symbol in info['defined'], 'Unrecognized GPU initializer: '+src.name)
            late_symbols.append(symbol)
            late = out/(src.stem+'.late.o')
            subprocess.run([objcopy, *('--remove-section='+s['segment']+','+s['name'] for s in init),
                            '--globalize-symbol='+symbol, obj, late], check=True, env=env)
            obj = late
        require(not initializers(macho(obj.read_bytes(), 1)), 'GPU has an automatic initializer')
        objects.append(obj)
        evidence.append(dict(source=src.name, source_sha256=sha(src), object_sha256=sha(obj)))

    for src in sources:
        compile_one(src)
    # All registration is late, after the working storage/display/touch boot
    # boundary. The worker is started once and terminates on completion/failure.
    init_source = out/'MyronGpuStart.cpp'
    text = '''#include <IOKit/IOLib.h>
#include <libkern/c++/OSMetaClass.h>
#include <kern/thread.h>
#include <mach/kmod.h>
#include <pexpert/pexpert.h>
extern "C" kmod_info_t g_kernel_kmod_info;
extern "C" void myron_gpu_run(void *, wait_result_t);
'''
    text += ''.join('extern "C" void gpu_init_'+str(i)+'() __asm__("'+s+'");\n'
                    for i, s in enumerate(late_symbols))
    text += '''extern "C" void myron_gpu_start(void) {
    unsigned enabled=0;
    if(!PE_parse_boot_argn("myron-gpu",&enabled,sizeof enabled) || enabled!=1)return;
    static unsigned started=0;
    if(__atomic_exchange_n(&started,1,__ATOMIC_ACQ_REL))return;
    void *handle=OSMetaClass::preModLoad(g_kernel_kmod_info.name);
    if(!handle)return;
'''
    text += ''.join('    gpu_init_'+str(i)+'();\n' for i in range(len(late_symbols)))
    text += '''    if(OSMetaClass::postModLoad(handle)!=KERN_SUCCESS)return;
    thread_t worker;
    if(kernel_thread_start(myron_gpu_run,nullptr,&worker)==KERN_SUCCESS)thread_deallocate(worker);
}
'''
    init_source.write_text(text)
    init_count = len(late_symbols)
    compile_one(init_source)
    require(len(late_symbols) == init_count, 'GPU boot entry unexpectedly needs its own initializer')
    for name in ('gmu', 'sqe', 'aqe', 'zap'):
        filename = next(n for n in pins if n.startswith('gen80200_'+name+'.'))
        symbol = '_myron_'+name+'_firmware'
        asm = out/('myron-'+name+'-firmware.S')
        asm.write_text('.section __DATA_CONST,__const\n.p2align 12\n.globl '+symbol+'\n'+symbol+':\n.incbin '+
                       json.dumps(str(firmware/filename))+'\n'+symbol+'_end:\n.p2align 3\n.globl '+symbol+'_size\n'+
                       symbol+'_size:\n.quad '+symbol+'_end-'+symbol+'\n')
        obj = asm.with_suffix('.o')
        subprocess.run(['xcrun', '--sdk', 'iphoneos', 'clang', *iphone_target_flags(env), '-c', asm, '-o', obj],
                       check=True, env=env)
        target.check_object(obj.read_bytes(), name+' firmware')
        objects.append(obj)
        evidence.append(dict(source=filename, source_sha256=pins[filename]['sha256'], object_sha256=sha(obj)))
    report.update(objects=evidence, late_initializers=late_symbols, native_objects_compiled=True)
    (out/'gpu-build.json').write_text(json.dumps(report, indent=2)+'\n')
    keep = ('_myron_gpu_start', '_myron_gpu_run', '_myron_gpu_ready', '_myron_gpu_stage',
            '_native_adreno_publish', '_native_adreno_new_user_client') + tuple(late_symbols)
    return objects, keep, report
