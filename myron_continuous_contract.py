"""Read native definitions from com.apple.kernel, not the outer fileset header."""
import struct

BUFFER_TRACE_MARKER = b'MYRON BUFFER TRACE 4 - release / completion'
BUFFER_TRACE_SYMBOLS = frozenset({
    '_myron_buffer_event', '_myron_boot_progress_panic',
    '_myron_boot_progress_fault', '_buf_brelse', '_buf_biodone',
    '_buf_getblk', '_buf_geteblk', '_buf_alloc', '_buf_free',
})

def require_buffer_trace(data):
    """Reject an old native payload even if its generic progress console exists."""
    definitions = kernel_definitions(data)
    missing = sorted(name for name in BUFFER_TRACE_SYMBOLS if not definitions.get(name))
    if missing or BUFFER_TRACE_MARKER not in data:
        raise ValueError(f'Buffer release/completion diagnostics missing: {missing}')
    return {name: definitions[name] for name in sorted(BUFFER_TRACE_SYMBOLS)}

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
