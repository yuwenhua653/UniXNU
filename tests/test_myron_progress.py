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
with tempfile.TemporaryDirectory() as tmp:
    root=Path(tmp)
    (root/'pexpert').mkdir();(root/'kern').mkdir()
    # Compile against the actual header after board patches, not a stale
    # extraction of only the OS profile's initial header definition.
    header_path='osfmk/kern/boot_progress.h'
    patches=[a.device/'upstream-overlay/profiles/os/ios-27.0.1-24A446-iphone12-1/patches/xnu/boot-progress.patch']
    series=a.device/'patches/xnu/series'
    for line in series.read_text().splitlines():
        line=line.strip()
        if not line or line.startswith('#'):continue
        assert ':' not in line, 'Resolve scoped board patch before testing'
        patches.append(series.parent/line)
    for patch in patches:
        text=patch.read_text()
        if '--- a/'+header_path in text or '+++ b/'+header_path in text:
            subprocess.run(['git','apply','--include='+header_path,str(patch.resolve())],cwd=root,check=True)
    (root/'kern/boot_progress.h').write_bytes((root/header_path).read_bytes())
    (root/'pexpert/pexpert.h').write_text('''#include <stddef.h>
#define kPEReleaseScreen 3
int PE_parse_boot_argn(const char *,void *,int);
int PE_initialize_console(void *,int);
''')
    if a.target_cc:
        import struct
        (root/'cross').mkdir()
        (root/'cross/string.h').write_text('#include <stddef.h>\nvoid *memset(void *,int,size_t);\nint strcmp(const char *,const char *);\nsize_t strlen(const char *);\n')
        # Xcode clang otherwise injects the host macOS SDK into an iPhone target.
        # Use only compiler builtin headers and explicit test fixtures on every host.
        resource=Path(subprocess.check_output([a.target_cc,'-print-resource-dir'],text=True).strip()).resolve()
        assert (resource/'include/stdint.h').is_file()
        sysroot=root/'freestanding-sysroot';sysroot.mkdir()
        obj=root/'progress.o'
        subprocess.run([a.target_cc,'-target','arm64e-apple-ios27.0','-ffreestanding','-mkernel',
            '-mgeneral-regs-only','-isysroot',str(sysroot),'-nostdinc','-isystem',str(resource/'include'),
            '-Wall','-Wextra','-Werror','-DMYRON_EARLY_PROGRESS=1',
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
#include <stdio.h>
static int format_calls, nested_format, fail_format;
#define vsnprintf observed_vsnprintf
#include "recorder.c"
#undef vsnprintf
int observed_vsnprintf(char *out,size_t size,const char *fmt,va_list args) {
 ++format_calls;
 assert(panic_claimed && myron_panic_pc==0xabc123);
 assert(strstr(display.previous[45],"EARLY PANIC"));
 if(nested_format) {
  myron_boot_progress_fault("nested while formatting",0xbad,1,2,3);
  assert(myron_panic_pc==0xabc123);
 }
 if(fail_format)return -1;
 return vsnprintf(out,size,fmt,args);
}
static void format_panic(const char *fmt,...) {
 va_list args;va_start(args,fmt);
 myron_boot_progress_panic_formatted(fmt,0xabc123,&args);
 // Check that the recorder copied, rather than consumed, original arguments.
 char after[1024];vsnprintf(after,sizeof(after),fmt,args);
 assert(strstr(after,"test-error=14") || strlen(after)==900);
 va_end(args);
}
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

 // Formatted panic keeps actual error/source values, original varargs and
 // first-fault fallback even if its formatter faults recursively.
 panic_claimed=0;
 myron_boot_object_failure(1,2,0,0xff1234);
 assert(object_failure.count==1 && object_failure.requested==0);
 nested_format=1;format_panic("test-error=%u source=%s:%d",14u,"AMFI",863);
 assert(format_calls==1 && strstr(display.previous[1],"test-error=14 source=AMFI:863"));
 assert(strstr(display.previous[10],"may be unrelated"));
 assert(strstr(display.previous[11],"kind=0x01 stage=0x02"));
 assert(strstr(display.previous[12],"0000000000ff1234"));
 myron_boot_object_failure(2,1,999,0xbad);assert(object_failure.count==1);
 format_panic("test-error=%u",14u);assert(format_calls==1);
 panic_claimed=0;nested_format=0;object_failure_busy=1;
 format_panic("test-error=%u",14u);
 assert(strstr(display.previous[10],"snapshot busy") && object_failure_busy);
 object_failure_busy=0;panic_claimed=0;
 char long_message[901];memset(long_message,'A',900);long_message[900]=0;
 format_panic("%s",long_message);
 assert(strstr(display.previous[0],"truncated") && strlen(display.previous[9])==31);
 panic_claimed=0;fail_format=1;format_panic("test-error=%u",14u);
 assert(strstr(display.previous[0],"formatter failed"));
 fail_format=0;panic_claimed=0;myron_boot_progress_panic_formatted(NULL,0xabc123,NULL);
 assert(panic_claimed && strstr(display.previous[45],"no format string"));
 panic_claimed=0;display.bound=0;unsigned calls_before=format_calls;
 format_panic("test-error=%u",14u);assert(!panic_claimed && format_calls==(int)calls_before);
 display.bound=1;enabled=0;
 format_panic("test-error=%u",14u);assert(!panic_claimed && format_calls==(int)calls_before);
 unsigned long long count_before=object_failure.count;
 myron_boot_object_failure(2,1,123,456);assert(object_failure.count==count_before);
 enabled=1;
 object_failure_busy=1;myron_boot_object_failure(2,1,123,456);
 assert(object_failure.count==count_before && object_failure_busy);object_failure_busy=0;
 myron_boot_object_failure(5,1,64,0x777);
 assert(object_failure.kind==5 && object_failure.stage==1 && object_failure.requested==64);
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
 // A contending refresh must not overwrite another reboot renderer.
 reboot_draw_busy=1;
 strcpy(first_row,display.previous[10]);draw_reboot();
 assert(!strcmp(first_row,display.previous[10])&&reboot_draw_busy);
 reboot_draw_busy=0;
 // Reboot provenance must survive shutdown churn and the later timer panic.
 // Preserve full logical lines across the 119-column console-ring wrapping.
 const char *plain="service started normally\nFeature disabled, device would have rebooted due to critical process crashes: example\n";
 for(const char *p=plain;*p;++p)boot_progress_putc(*p);
 assert(!shutdown_log_count);
 for(unsigned i=0;i<140;i++)boot_progress_putc('p');
 const char *why=" SYSTEM REBOOT initiated by: test-service (pid 41)\n";
 for(const char *p=why;*p;++p)boot_progress_putc(*p);
 assert(shutdown_log_count==1 && strstr(shutdown_log_rows[0][1],"test-service"));
 const char *why2="launchd: committing to system shutdown\n";
 for(const char *p=why2;*p;++p)boot_progress_putc(*p);
 assert(shutdown_log_count==2);
 // Inputs are bounded; a missing newline cannot overrun static storage.
 const char *why3="rebooting due to fixture: ";
 for(const char *p=why3;*p;++p)boot_progress_putc(*p);
 for(unsigned i=0;i<1200;i++)boot_progress_putc('z');
 boot_progress_putc('\n');assert(shutdown_log_count==3);
 assert(strstr(shutdown_log_rows[2][1],"..."));
 char original_logs[sizeof(shutdown_log_rows)];memcpy(original_logs,shutdown_log_rows,sizeof original_logs);
 for(const char *p=why;*p;++p)boot_progress_putc(*p);
 assert(!memcmp(original_logs,shutdown_log_rows,sizeof original_logs));
 boot_progress_stage("before-reboot marker");
 assert(myron_boot_reboot_request(1,1,"launchd",0x80,0,0x123456,"reason text")==1);
 assert(reboot_visible() && reboot_first==1 && reboot_history_available && !reboot_draw_busy);
 reboot_draw_busy=1;strcpy(first_row,display.previous[10]);draw_reboot();
 assert(!strcmp(first_row,display.previous[10])&&reboot_draw_busy);reboot_draw_busy=0;
 assert(reboot_requests[0].pid==1 && reboot_requests[0].options==0x80);
 assert(strstr(display.previous[10],"FIRST REBOOT REQUEST"));
 assert(strstr(display.previous[12],"launchd"));
 assert(strstr(display.previous[33],"EARLY SHUTDOWN LOGS"));
 assert(strstr(display.previous[35],"test-service"));
 // Freeze is independent of capacity: late messages cannot fill an empty slot.
 shutdown_log_count=1;
 for(const char *p=why2;*p;++p)boot_progress_putc(*p);
 assert(shutdown_log_count==1);shutdown_log_count=3;
 char retained[sizeof(reboot_history)];memcpy(retained,reboot_history,sizeof(retained));
 assert(myron_boot_reboot_request(1,77,"overwrite",0xff,1,0xbad,"overwrite")==0);
 assert(reboot_requests[0].caller==0x123456 && !strcmp(reboot_requests[0].message,"reason text"));
 myron_boot_reboot_request(3,-1,"host_reboot",4,0,0x234567,NULL);
 myron_boot_reboot_request(4,-1,"PEHaltRestartInternal",1,7,0x345678,NULL);
 assert(reboot_first==1 && reboot_ready[2] && reboot_ready[3]);
 struct boot_progress_exit_trace reboot_bt={0};reboot_bt.count=20;reboot_bt.cache_slide=0x9000;
 for(unsigned i=0;i<20;++i)reboot_bt.frames[i]=0x1000+4*i;
 myron_boot_reboot_trace(&reboot_bt);assert(reboot_trace.count==8);
 assert(strstr(display.previous[32],"000000000000101c"));
 myron_boot_shutdown_stage("driver ack wait","TestDriver",0x999,0x888);
 assert(strstr(display.previous[18],"driver ack wait"));
 for(unsigned i=0;i<30;++i) {boot_progress_stage("shutdown churn");boot_progress_putc('\n');}
 assert(!memcmp(retained,reboot_history,sizeof(retained)));
 test_clock+=1000;boot_progress_irq(0x101,0x202,0x303);
 assert(strstr(display.previous[18],"driver ack wait"));
 format_panic("test-error=14 Halt/Restart Timed Out");
 assert(strstr(display.previous[0],"PANIC DETAIL"));
 assert(strstr(display.previous[10],"FIRST REBOOT REQUEST"));
 assert(strstr(display.previous[44],"reason text"));
 assert(strstr(display.previous[35],"test-service"));
 assert(!memcmp(original_logs,shutdown_log_rows,sizeof original_logs));
 myron_boot_shutdown_stage("panic overwrites","wrong",1,1);
 assert(!strcmp(shutdown_phase,"driver ack wait"));
 panic_claimed=0;reboot_first=0;
 // The no-matching-log fallback remains honest, including contended capture.
 shutdown_log_count=0;
 memset(reboot_claimed,0,sizeof(reboot_claimed));memset(reboot_ready,0,sizeof(reboot_ready));
 reboot_history_ready=0;reboot_history_available=0;busy=1;
 myron_boot_reboot_request(2,0,NULL,0,0,0,NULL);
 assert(reboot_visible() && !reboot_history_available && busy==1);
 assert(strstr(display.previous[33],"unavailable"));busy=0;
 shutdown_busy=1;myron_boot_shutdown_stage("must not wait","",1,1);
 assert(shutdown_busy==1 && !strcmp(shutdown_phase,"driver ack wait"));shutdown_busy=0;
 reboot_first=0;memset(reboot_claimed,0,sizeof(reboot_claimed));memset(reboot_ready,0,sizeof(reboot_ready));
 myron_boot_reboot_request(0,0,NULL,0,0,0,NULL);myron_boot_reboot_request(5,0,NULL,0,0,0,NULL);
 assert(!reboot_first);
 // Release failure may retry; acknowledged scanout cannot resume console writes.
 release_result=-1;assert(!myron_boot_progress_prepare_scanout());assert(scanout_state==1);
 release_result=0;assert(myron_boot_progress_prepare_scanout());assert(scanout_state==2 && release_calls==2);
 unsigned char *saved=malloc(bytes);assert(saved);memcpy(saved,memory+32,bytes);
 myron_boot_progress_cancel_scanout();boot_progress_stage("userspace owns display");boot_progress_putc('\n');
 myron_mount_event(1,"scanout active","apfs",0,0);test_clock+=1000;boot_progress_irq(0,0,0);
 myron_boot_progress_fault("scanout owns display",1,2,3,4);assert(!panic_claimed);
 myron_buffer_event(255,0xa000,0x707,0,0,0,0);assert(!panic_claimed);
 myron_boot_reboot_request(1,1,"scanout",0,0,0,NULL);
 myron_boot_shutdown_stage("scanout","",0,0);
 assert(!reboot_first);
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
print('PASS earliest shutdown console reasons, wrapping/truncation/non-reboot control and freeze; first reboot source/options/history/user trace, shutdown phases and timeout retention; formatted panic arguments/truncation/nesting, object-failure snapshots, typed buffer ownership/history, bounded ring wrap, contended writer, first-panic retention, lock-independent IRQ rows, early/recursive panic, scanout ownership, persistent mount phases, dropped-event accounting, IRQ refresh, continuous execution past deadlines, bounded rendering, invalid mapping rejection and scanout handoff')
