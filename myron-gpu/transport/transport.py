"""Lossless MYRKERN1 file transport, never edits the decoded Mach-O bytes."""
import hashlib,struct,zlib
BLOCK=65536
MAX=128*1024*1024
HEADER=96
ENTRY=struct.Struct('<QIIII')
def require(ok,why):
 if not ok:raise ValueError(why)
def digest(b):return hashlib.sha256(b).hexdigest()
def pack(raw):
 import lz4.block
 require(32<=len(raw)<=MAX and raw[:4]==bytes.fromhex('cffaedfe'),'Require bounded Mach-O')
 chunks=[raw[a:a+BLOCK] for a in range(0,len(raw),BLOCK)];table=bytearray();body=[];at=HEADER+len(chunks)*ENTRY.size
 for block in chunks:
  data=lz4.block.compress(block,mode='high_compression',compression=9,store_size=False)
  flags=int(len(data)<len(block));data=data if flags else block
  table+=ENTRY.pack(at,len(data),len(block),zlib.crc32(block),flags);body.append(data);at+=len(data)
 h=struct.pack('<8sIIQQII32sI20s',b'MYRKERN1',1,BLOCK,len(raw),at,len(chunks),ENTRY.size,hashlib.sha256(raw).digest(),zlib.crc32(table),bytes(20))
 out=h+bytes(table)+b''.join(body)
 require(unpack(out)==raw,'Transport roundtrip mismatch')
 return out
def unpack(data):
 if data[:8]!=b'MYRKERN1':return data
 import lz4.block
 require(len(data)>=HEADER,'Short transport')
 magic,v,block,logical,total,count,entry,sha,crc,reserved=struct.unpack_from('<8sIIQQII32sI20s',data)
 require(v==1 and block==BLOCK and 32<=logical<=MAX and total==len(data) and count==(logical+BLOCK-1)//BLOCK and entry==24 and not any(reserved),'Transport header')
 at=HEADER+count*entry;require(at<=total,'Transport index bounds')
 table=data[HEADER:at];require(zlib.crc32(table)==crc,'Transport index CRC')
 out=bytearray()
 for i in range(count):
  offset,n,size,check,flags=ENTRY.unpack_from(table,i*entry)
  require(offset==at and size==min(BLOCK,logical-i*BLOCK) and 0<n<=size and flags in (0,1) and (n==size if not flags else n<size) and n<=total-at,'Transport entry')
  packed=data[at:at+n];raw=lz4.block.decompress(packed,uncompressed_size=size) if flags else packed
  require(len(raw)==size and zlib.crc32(raw)==check,'Transport block integrity');out+=raw;at+=n
 require(at==total and hashlib.sha256(out).digest()==sha,'Decoded kernel identity')
 return bytes(out)
