"""Read native definitions from com.apple.kernel, not the outer fileset header."""
import struct

BUFFER_TRACE_MARKER = b'MYRON BUFFER TRACE 4 - release / completion'
REBOOT_TRACE_MARKER = b'FIRST REBOOT REQUEST'
# append_text() is inlined by Apple clang: the heading can become MOVK/STP
# instructions rather than a contiguous C string. Require the actual matcher,
# retained state and its reason strings instead of depending on literal layout.
CONSOLE_ROUTE_MARKER = b'BUFFERED CONSOLE ROUTE 1'
SHUTDOWN_LOG_MARKER = b'EARLY SHUTDOWN LOGS (unverified)'
SHUTDOWN_LOG_REASON_MARKERS = (
    b'system reboot initiated by:', b'system shutdown initiated by:',
    b'critical process crashes:', b'feature disabled, device would have rebooted',
)
SHUTDOWN_LOG_SYMBOLS = frozenset({
    '_shutdown_log_match.phrases', '_shutdown_log_count',
    '_shutdown_log_times', '_shutdown_log_rows', '_shutdown_log_used',
    '_shutdown_log_line', '_shutdown_log_overflow', '_draw_reboot',
})
# Optimizing clang may inline shutdown_log_match into capture_console. The
# new layout must retain the independent capture state as well as all common
# reason strings/state; absence of an out-of-line helper alone is not a defect.
SHUTDOWN_LOG_LEGACY_SYMBOLS = frozenset({'_shutdown_log_match'})
SHUTDOWN_LOG_CAPTURE_SYMBOLS = frozenset({
    '_capture_console', '_console_capture_busy', '_console_capture_gap',
    '_console_capture_dropped', '_persist_console', '_persist_console_head',
})
BUFFER_TRACE_SYMBOLS = frozenset({
    '_myron_boot_console_write', '_myron_console_route_calls',
    '_myron_console_route_bytes', '_myron_console_route_muted', '_myron_console_route_dropped',
    '_myron_boot_log_snapshot', '_myron_log_state', '_myron_log_rounds', '_myron_log_errors', '_myron_log_first_lba',
    '_myron_boot_reboot_request', '_myron_boot_reboot_trace', '_myron_boot_shutdown_stage',
    '_myron_buffer_event', '_myron_boot_progress_panic', '_myron_boot_progress_panic_formatted', '_myron_boot_object_failure',
    '_myron_boot_progress_fault', '_buf_brelse', '_buf_biodone',
    '_buf_getblk', '_buf_geteblk', '_buf_alloc', '_buf_free',
}) | SHUTDOWN_LOG_SYMBOLS
EXIT_TRACE_MARKER = b'SIGABRT: PID 1 exiting thread user backtrace'
EXIT_TRACE_SYMBOLS = frozenset({'_boot_progress_exit_trace', '_backtrace_user', '_boot_progress_current_cache_slide'})
LOCKDOWN_STATE_SYMBOLS = frozenset({'_sysctl__security_mac_lockdown_mode_state_public',
    '_sysctl_lockdown_mode_state_public', '_get_lockdown_mode_state'})

DISPLAY_SYMBOLS = frozenset({'_myron_display_start','_myron_display_snapshot',
    '__ZTV19NativeLegacyDisplay','_native_legacy_display_allocate',
    '_native_legacy_default_surface_create','_native_legacy_prepare_scanout'})
DISPLAY_ARGUMENTS = frozenset({'myron27-display=1','offline-legacy-phase=4',
    'offline-legacy-register=1','offline-legacy-gop=1','offline-legacy-validate=1',
    'offline-legacy-transfer=1','offline-legacy-retire=1','offline-legacy-cpu-present=1'})

def require_cpu_display(data):
    definitions=kernel_definitions(data)
    missing=sorted(DISPLAY_SYMBOLS-definitions.keys())
    if missing:raise ValueError(f'CPU GOP display backend missing from final payload: {missing}')
    return {name:definitions[name] for name in sorted(DISPLAY_SYMBOLS)}

def require_lockdown_state(data):
    """Require the public state OID and implementation in the final kernel."""
    definitions = kernel_definitions(data)
    missing = sorted(name for name in LOCKDOWN_STATE_SYMBOLS if not definitions.get(name))
    if missing:
        raise ValueError(f'Public Lockdown Mode state ABI missing: {missing}')
    return {name: definitions[name] for name in sorted(LOCKDOWN_STATE_SYMBOLS)}

def require_exit_trace(data):
    """Require the new SIGABRT recorder in the final nested kernel payload."""
    definitions = kernel_definitions(data)
    missing = sorted(name for name in EXIT_TRACE_SYMBOLS if not definitions.get(name))
    if missing or EXIT_TRACE_MARKER not in data:
        raise ValueError(f'SIGABRT exit backtrace diagnostics missing: {missing}')
    return {name: definitions[name] for name in sorted(EXIT_TRACE_SYMBOLS)}

def require_buffer_trace(data):
    """Reject an old native payload even if its generic progress console exists."""
    definitions = kernel_definitions(data)
    missing = sorted(name for name in BUFFER_TRACE_SYMBOLS if not definitions.get(name))
    markers = (BUFFER_TRACE_MARKER, REBOOT_TRACE_MARKER, CONSOLE_ROUTE_MARKER, *SHUTDOWN_LOG_REASON_MARKERS)
    missing_markers = [marker.decode('ascii') for marker in markers if marker not in data]
    variants = (SHUTDOWN_LOG_LEGACY_SYMBOLS, SHUTDOWN_LOG_CAPTURE_SYMBOLS)
    implementation = next((symbols for symbols in variants
                           if all(definitions.get(name) for name in symbols)), None)
    if missing or missing_markers or implementation is None:
        absent = [sorted(name for name in symbols if not definitions.get(name)) for symbols in variants]
        raise ValueError(f'Buffer/reboot diagnostics missing: symbols={missing}; markers={missing_markers}; matcher_variants={absent}')
    return {name: definitions[name] for name in sorted(BUFFER_TRACE_SYMBOLS | implementation)}

def kernel_definitions(data):
    def need(ok,message):
        if not ok: raise ValueError(message)
    def commands(at,kind):
        need(0<=at<=len(data)-32,'Truncated Mach-O header')
        magic,cpu,subtype,actual,count,size=struct.unpack_from('<6I',data,at)
        need((magic,cpu,subtype&0xffffff,actual)==(0xfeedfacf,0x100000c,2,kind),'Wrong arm64e image kind')
        pos=at+32;end=pos+size
        need(end<=len(data) and count<=size//8,'Truncated Mach-O commands')
        rows=[]
        for _ in range(count):
            need(pos+8<=end,'Truncated command')
            cmd,length=struct.unpack_from('<II',data,pos)
            need(length>=8 and pos+length<=end,'Invalid command extent')
            rows.append((cmd,pos,length));pos+=length
        need(pos==end,'Inconsistent command table')
        return rows
    matches=[]
    for cmd,pos,length in commands(0,12):
        if cmd!=0x80000035:continue
        need(length>=32,'Short fileset entry')
        _,offset,name=struct.unpack_from('<QQI',data,pos+8)
        need(32<=name<length,'Invalid fileset identifier')
        stop=data.find(b'\0',pos+name,pos+length)
        need(stop>=0,'Unterminated fileset identifier')
        if data[pos+name:stop]==b'com.apple.kernel':matches.append(offset)
    need(len(matches)==1,'Require one com.apple.kernel fileset member')
    tables=[(pos,length) for cmd,pos,length in commands(matches[0],2) if cmd==2]
    need(len(tables)==1 and tables[0][1]==24,'Native kernel symbol table missing')
    off,count,strings,size=struct.unpack_from('<4I',data,tables[0][0]+8)
    need(off+count*16<=len(data) and strings+size<=len(data),'Truncated native symbol data')
    result={}
    for i in range(count):
        ix,typ,section,_,value=struct.unpack_from('<IBBHQ',data,off+16*i)
        if not ix or typ&0xe0 or typ&0xe!=0xe or not section:continue
        need(ix<size,'Native symbol name outside string table')
        stop=data.find(b'\0',strings+ix,strings+size)
        need(stop>=0,'Unterminated native symbol name')
        result[data[strings+ix:stop].decode()]=value
    return result


