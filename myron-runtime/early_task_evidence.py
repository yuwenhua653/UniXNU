"""Retain bounded early task checkpoints without changing boot or disk policy."""
from pathlib import Path
import shutil

def apply(board, replace):
    package=board/'package'
    shutil.copyfile(Path(__file__).with_name('MyronEarlyTaskLog.h'),package/'MyronEarlyTaskLog.h')
    replace(package/'MyronRebootEvidence.h','static char persist_console[32768];',
        '#include "MyronEarlyTaskLog.h"\nstatic char persist_console[32768];')
    replace(package/'MyronRebootEvidence.h','static void shutdown_log_char(char c) {',
        'static void shutdown_log_char(char c) {\n'
        ' if(!__atomic_load_n(&reboot_first,__ATOMIC_ACQUIRE) && !__atomic_load_n(&panic_claimed,__ATOMIC_ACQUIRE))early_task_char(c);')
    replace(package/'MyronRebootEvidence.h',' if(__atomic_exchange_n(&console_capture_gap,0,__ATOMIC_ACQ_REL)) {',
        ' if(__atomic_exchange_n(&console_capture_gap,0,__ATOMIC_ACQ_REL)) {\n  early_task_gap();')
    replace(package/'MyronLogSnapshot.h','  log_number(out,cap,&at,"console_captured_bytes=",persist_console_head);',
        '''  log_text(out,cap,&at,"[retained early task checkpoints; console hints only]\\n");
  log_number(out,cap,&at,"early_task_lines=",early_task_count);
  log_number(out,cap,&at,"early_task_truncated=",early_task_truncated);
  log_number(out,cap,&at,"early_task_capture_gaps=",early_task_gaps);
  for(uint64_t i=0;i<early_task_count && i<12;++i) {
   log_text(out,cap,&at,early_task_first[i]);log_text(out,cap,&at,"\\n");
  }
  uint64_t early_begin=early_task_count>16?early_task_count-4:12;
  for(uint64_t i=early_begin;i<early_task_count;++i) {
   log_text(out,cap,&at,early_task_tail[(i-12)%4]);log_text(out,cap,&at,"\\n");
  }
  log_number(out,cap,&at,"console_captured_bytes=",persist_console_head);''')
    replace(package/'MyronLogSnapshot.h',' log_number(out,cap,&at,"first_reboot=",',
        ' log_number(out,cap,&at,"scanout_enabled=",enabled);\n'
        ' log_number(out,cap,&at,"scanout_state=",__atomic_load_n(&scanout_state,__ATOMIC_ACQUIRE));\n'
        ' log_number(out,cap,&at,"scanout_prepare_calls=",myron_scanout_prepare_calls);\n'
        ' log_number(out,cap,&at,"scanout_cancel_calls=",myron_scanout_cancel_calls);\n'
        ' log_number(out,cap,&at,"scanout_release_status=",(uint32_t)myron_scanout_release_status);\n'
        ' log_number(out,cap,&at,"first_reboot=",')
