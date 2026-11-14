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
 // The IRQ-only rows continue even when the normal writer is held.
 busy=1;test_clock+=1000;boot_progress_irq(0xabc,0x3c5,0x123);
 assert(myron_irq_pc==0xabc && myron_irq_psr==0x3c5 && myron_irq_sp==0x123);
 assert(strstr(display.previous[25],"console=BUSY") && irq_refresh==seconds());
 assert(mount_refresh!=seconds());busy=0;
 myron_boot_progress_irq_return();assert(myron_irq_returns==1);
 // A pending independent writer must drain before display handoff succeeds.
 irq_busy=1;assert(!myron_boot_progress_prepare_scanout());assert(scanout_state==1 && !release_calls);
 myron_boot_progress_fault("handoff pending",1,2,3,4);assert(!panic_claimed);
 irq_busy=0;myron_boot_progress_cancel_scanout();assert(!scanout_state);
 // A real early panic bypasses the stuck normal writer; nested panic preserves
 // the first numeric fault record and does not recurse into display output.
 busy=1;myron_boot_progress_fault("fatal test",0x100,0x200,0x96000004,0x300);
 assert(panic_claimed && myron_panic_pc==0x100 && myron_panic_lr==0x200);
 assert(myron_panic_esr==0x96000004 && myron_panic_far==0x300);
 assert(strstr(display.previous[45],"fatal test") && strstr(display.previous[46],"00000100"));
 myron_boot_progress_panic("nested %s",0x999);assert(myron_panic_pc==0x100);
 assert(!myron_boot_progress_prepare_scanout());busy=0;
 panic_claimed=0; // isolated test of the ordinary-panic path
 myron_boot_progress_panic("ordinary format %s",0x444);
 assert(myron_panic_pc==0x444 && !myron_panic_lr && !myron_panic_esr && !myron_panic_far);
 assert(strstr(display.previous[45],"ordinary format %s"));
 panic_claimed=0;display.bound=0;myron_boot_progress_panic("unbound",1);assert(!panic_claimed);display.bound=1;
 // Fault rows preserve both frame guards and padded scanline bytes.
 for(size_t i=0;i<32;i++)assert(memory[i]==0xa5 && memory[bytes+32+i]==0xa5);
 for(size_t y=0;y<1500;y++)for(size_t x=720*4;x<736*4;x++)assert(memory[32+y*736*4+x]==0xa5);
 // A failed release reports only this buffer's history, newest first, with
 // the original ownership fields and call sites preserved across interleaving.
 myron_buffer_event(1,0xa000,0x101,~0u,1,0x100,0x20);
 myron_buffer_event(1,0xb000,0xb01,~0u,1,0x100,0x30);
 myron_buffer_event(2,0xa000,0x202,~0u,1,0x20100,0x20);
 myron_buffer_event(3,0xa000,0x303,0,0,0x20100,0x20);
 busy=1;myron_buffer_event(255,0xa000,0x404,0,0,0x20100,0x20);
 assert(panic_claimed && myron_panic_pc==0x404 && !buffer_busy);
 assert(strstr(display.previous[28],"000000000000a000"));
 assert(strstr(display.previous[29],"LF=0x0000000000000000"));
 assert(strstr(display.previous[31],"00000303") && strstr(display.previous[34],"00000202"));
 assert(strstr(display.previous[37],"00000101") && !display.previous[40][0]);
 char first_row[BP_COLS];strcpy(first_row,display.previous[31]);
 myron_boot_progress_panic("original panic",0x555);
 test_clock+=1000;boot_progress_irq(9,8,7);busy=0;boot_progress_stage("late log");
 assert(myron_panic_pc==0x404 && !strcmp(first_row,display.previous[31]));
 // Contended capture cannot spin or pretend to have a complete history.
 panic_claimed=0;buffer_busy=1;
 myron_buffer_event(255,0xa000,0x505,~0u,0,0,0);
 assert(myron_panic_pc==0x505 && buffer_busy && buffer_dropped==1);
 assert(strstr(display.previous[30],"history omitted") && !display.previous[31][0]);
 buffer_busy=0;panic_claimed=0;
 // A callback taking ownership and a filter have different release contracts.
 // The recorder labels their function targets separately from call sites.
 myron_buffer_event(7,0xd000,0x707,~0u,1,0x200,0x40);
 myron_buffer_event(8,0xd000,0x808,~0u,1,0x200,0x40);
 myron_buffer_event(255,0xd000,0x909,0,0,0x200,0x40);
 assert(strstr(display.previous[31],"CALLBACK=") && strstr(display.previous[31],"00000808"));
 assert(strstr(display.previous[34],"CALLBACK=") && strstr(display.previous[34],"00000707"));
 assert(!display.previous[37][0]);panic_claimed=0;
 // Ring wrap discards old entries explicitly; unknown buffers produce no
 // fabricated history. No record stores a dereferenceable pointer.
 for(unsigned i=0;i<MYRON_BUFFER_HISTORY+3;i++)myron_buffer_event(1,0xc000,i,~0u,1,0,0);
 myron_buffer_event(255,0xa000,0x606,0,0,0,0);
 assert(strstr(display.previous[31],"No matching buffer"));
 panic_claimed=0;
 for(size_t i=0;i<32;i++)assert(memory[i]==0xa5 && memory[bytes+32+i]==0xa5);
 for(size_t y=0;y<1500;y++)for(size_t x=720*4;x<736*4;x++)assert(memory[32+y*736*4+x]==0xa5);
 // Release failure may retry; acknowledged scanout cannot resume console writes.
 release_result=-1;assert(!myron_boot_progress_prepare_scanout());assert(scanout_state==1);
 release_result=0;assert(myron_boot_progress_prepare_scanout());assert(scanout_state==2 && release_calls==2);
 unsigned char *saved=malloc(bytes);assert(saved);memcpy(saved,memory+32,bytes);
 myron_boot_progress_cancel_scanout();boot_progress_stage("userspace owns display");boot_progress_putc('\n');
 myron_mount_event(1,"scanout active","apfs",0,0);test_clock+=1000;boot_progress_irq(0,0,0);
 myron_boot_progress_fault("scanout owns display",1,2,3,4);assert(!panic_claimed);
 myron_buffer_event(255,0xa000,0x707,0,0,0,0);assert(!panic_claimed);
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
print('PASS typed buffer ownership/history, bounded ring wrap, contended writer, first-panic retention, lock-independent IRQ rows, early/recursive panic, scanout ownership, persistent mount phases, dropped-event accounting, IRQ refresh, continuous execution past deadlines, bounded rendering, invalid mapping rejection and scanout handoff')
