#!/usr/bin/env python3
"""Exercise the actual recorder, including continued boot and framebuffer ownership."""
import argparse
import os
from pathlib import Path
import subprocess
import tempfile

p=argparse.ArgumentParser()
p.add_argument('--device', type=Path, required=True)
p.add_argument('--cc', default='cc')
p.add_argument('--target-cc', help='Optional Clang binary for an independent arm64e compile')
a=p.parse_args()
source=a.device/'package/MyronBootProgress.c'
patch=(a.device/'upstream-overlay/profiles/os/ios-27.0.1-24A446-iphone12-1/patches/xnu/boot-progress.patch').read_text()
header=patch.split('+++ b/osfmk/kern/boot_progress.h\n',1)[1].split('diff --git',1)[0]
header='\n'.join(l[1:] for l in header.splitlines() if l.startswith('+'))+'\n'
header=header.replace('#if defined(XNU_BOOT_PROGRESS) && XNU_BOOT_PROGRESS','#if defined(MYRON_EARLY_PROGRESS)')
with tempfile.TemporaryDirectory() as tmp:
    root=Path(tmp)
    (root/'pexpert').mkdir();(root/'kern').mkdir()
    (root/'kern/boot_progress.h').write_text(header)
    (root/'pexpert/pexpert.h').write_text('''#include <stddef.h>
#define kPEReleaseScreen 3
int PE_parse_boot_argn(const char *,void *,int);
int PE_initialize_console(void *,int);
''')
    if a.target_cc:
        import struct
        (root/'cross').mkdir()
        (root/'cross/string.h').write_text('#include <stddef.h>\nvoid *memset(void *,int,size_t);\nint strcmp(const char *,const char *);\nsize_t strlen(const char *);\n')
        obj=root/'progress.o'
        subprocess.run([a.target_cc,'-target','arm64e-apple-ios27.0','-ffreestanding','-mkernel',
            '-mgeneral-regs-only','-Wall','-Wextra','-Werror','-DMYRON_EARLY_PROGRESS=1',
            '-I',str(root),'-I',str(root/'cross'),'-c',str(source.resolve()),'-o',str(obj)],check=True)
        raw=obj.read_bytes();magic,cpu,subtype,kind=struct.unpack_from('<4I',raw)
        assert (magic,cpu,subtype & 0xffffff,kind)==(0xfeedfacf,0x100000c,2,1)
        print('PASS independent arm64e recorder cross-compile (full native SDK ABI checked in native job)')
    text=source.read_text()
    # Only CPU register reads are substituted in this host execution.
    for old,new in [
      ('__asm__ volatile("mrs %0, cntvct_el0":"=r"(t));','t=test_clock;'),
      ('__asm__ volatile("mrs %0, cntfrq_el0":"=r"(frequency));','frequency=test_frequency;'),
      ('__asm__ volatile("mrs %0, cntvct_el0":"=r"(epoch));','epoch=test_clock;')]:
        assert text.count(old)==1; text=text.replace(old,new)
    (root/'recorder.c').write_text('static unsigned long long test_clock, test_frequency=1000;\n'+text)
    test=r'''
#include <assert.h>
#include <stdlib.h>
#include <string.h>
#include "recorder.c"
static int option=2,release_result,release_calls;
int PE_parse_boot_argn(const char *key,void *out,int size) {
 assert(!strcmp(key,"boot-progress") && size==sizeof(unsigned));
 *(unsigned *)out=option;return 1;
}
int PE_initialize_console(void *p,int op) {
 assert(!p && op==kPEReleaseScreen);++release_calls;
 boot_progress_stage("recursive console release");return release_result;
}
int main(void) {
 option=0;boot_progress_init();assert(!boot_progress_active());
 option=2;boot_progress_init();assert(boot_progress_active());
 // Boot milestones remain writable beyond both historical timeouts.
 boot_progress_stage("C initialized");test_clock=1000000;boot_progress_poll();
 assert(!myron_boot_progress_state.frozen && myron_boot_progress_state.reason==2);
 boot_progress_stage("mount succeeded");boot_progress_putc('Z');
 assert(myron_boot_progress_state.history_count==3 && myron_boot_progress_state.logs[0][0]=='Z');
 unsigned history=myron_boot_progress_state.history_count;
 boot_progress_user_abort(NULL,0x92000004,0x1234000);
 assert(myron_boot_progress_state.history_count==history && myron_user_abort_count==1);
 assert(myron_last_user_abort_esr==0x92000004 && myron_last_user_abort_far==0x1234000);
 // Reject unmapped/overflowing/invalid video geometry before any framebuffer store.
 boot_progress_bind(0x1000,1200,2608,4800,32);assert(!display.bound);
 boot_progress_bind(UINTPTR_MAX-4096,1200,2608,4800,32);assert(!display.bound);
 boot_progress_bind(0xfffffff000000000ULL,1200,2608,4799,32);assert(!display.bound);
 // Use a real host buffer to execute rendering and preserve guard/padding bytes.
 size_t bytes=736*4*1500;unsigned char *memory=malloc(bytes+64);assert(memory);
 memset(memory,0xa5,bytes+64);
 display.frame=(uintptr_t)(memory+32);display.width=720;display.height=1500;
 display.stride=736*4;display.scale=2;display.bound=1;
 bp_clear(&display);boot_progress_stage("draw test");
 for(size_t i=0;i<32;i++)assert(memory[i]==0xa5 && memory[bytes+32+i]==0xa5);
 for(size_t y=0;y<1500;y++)for(size_t x=720*4;x<736*4;x++)assert(memory[32+y*736*4+x]==0xa5);
 // Root/VFS/transport/request facts survive history and console rollover.
 myron_mount_event(0,"root returned","disk0s1",0x1000001,0);
 myron_mount_event(1,"mount callback enter","apfs",0x1000001,0);
 myron_mount_event(4,"request enter","OS",8192,8);
 for(unsigned i=0;i<40;i++){boot_progress_stage("rolling stage");boot_progress_putc('\n');}
 assert(!strcmp(myron_mount_slots[0].name,"disk0s1") && myron_mount_slots[0].a==0x1000001);
 assert(!strcmp(myron_mount_slots[1].name,"apfs") && myron_mount_slots[1].b==0);
 assert(!strcmp(myron_mount_slots[4].name,"OS") && myron_mount_slots[4].a==8192);
 busy=1;myron_mount_event(1,"dropped","",0,0);busy=0;
 assert(myron_mount_dropped==1 && !strcmp(myron_mount_slots[1].phase,"mount callback enter"));
 char long_name[1000];memset(long_name,'X',sizeof(long_name));long_name[999]=0;
 myron_mount_event(2,"copy returned",long_name,4096,4096);
 assert(strlen(myron_mount_slots[2].name)==BP_COLS-1);
 myron_mount_event(100,"invalid","",0,0);assert(myron_mount_dropped==1);
 test_clock+=1000;boot_progress_irq(0,0,0);assert(mount_refresh==seconds());
 unsigned refresh=mount_refresh;boot_progress_irq(0,0,0);assert(mount_refresh==refresh);
 // All five rows and the heartbeat fit; padding/guard bytes remain intact.
 for(size_t i=0;i<32;i++)assert(memory[i]==0xa5 && memory[bytes+32+i]==0xa5);
 for(size_t y=0;y<1500;y++)for(size_t x=720*4;x<736*4;x++)assert(memory[32+y*736*4+x]==0xa5);
 // Release failure may retry; acknowledged scanout cannot resume console writes.
 release_result=-1;assert(!myron_boot_progress_prepare_scanout());assert(scanout_state==1);
 release_result=0;assert(myron_boot_progress_prepare_scanout());assert(scanout_state==2 && release_calls==2);
 unsigned char *saved=malloc(bytes);assert(saved);memcpy(saved,memory+32,bytes);
 myron_boot_progress_cancel_scanout();boot_progress_stage("userspace owns display");boot_progress_putc('\n');
 myron_mount_event(1,"scanout active","apfs",0,0);test_clock+=1000;boot_progress_irq(0,0,0);
 assert(scanout_state==2 && !memcmp(saved,memory+32,bytes));
 boot_progress_exit(1,"launchd",9,3,0xdead);assert(myron_boot_progress_state.history_count>history);
 // Missing timer frequency must not turn the recorder or boot path off.
 frequency=0;assert(seconds()==0 && boot_progress_active());
 free(saved);free(memory);
 return 0;
}
'''
    (root/'test.c').write_text(test)
    subprocess.run([a.cc,'-std=c11','-Wall','-Wextra','-Werror','-DMYRON_EARLY_PROGRESS=1','-fsanitize=address,undefined','-fno-omit-frame-pointer',
                    '-I',str(root),'-I',str(source.parent.resolve()),str(root/'test.c'),'-o',str(root/'test')],check=True)
    subprocess.run([str(root/'test')],check=True,env=dict(os.environ,ASAN_OPTIONS='detect_leaks=0'),timeout=20)
print('PASS persistent mount phases, dropped-event accounting, IRQ refresh, continuous execution past deadlines, bounded rendering, invalid mapping rejection and scanout handoff')
