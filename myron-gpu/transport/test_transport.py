#!/usr/bin/env python3
"""Exercise the actual EFI transport/parser with an independently pinned Mach-O."""
import argparse, hashlib, os, random, struct, subprocess, sys, tempfile, zlib
from pathlib import Path
from transport import pack, unpack, BLOCK
p=argparse.ArgumentParser();p.add_argument('--device',type=Path,required=True);p.add_argument('--kernel',type=Path,required=True)
p.add_argument('--sha256',required=True);p.add_argument('--cc',default='gcc');a=p.parse_args()
raw=a.kernel.read_bytes();assert hashlib.sha256(raw).hexdigest()==a.sha256
packed=pack(raw);assert unpack(packed)==raw
here=Path(__file__).resolve().parent
with tempfile.TemporaryDirectory(prefix='myron-packed-') as tmp:
 t=Path(tmp);(t/'kernel.packed').write_bytes(packed)
 base=(a.device/'tests/kernel_stream_host.c').read_text()
 prefix=base[:base.index('static UINTN rejected_mutations;')]
 prefix=prefix.replace('#include "KernelStream.h"','#include "MyronPackedKernel.h"\n#include "KernelStream.h"')
 prefix=prefix.replace('#include "OriginalParser.h"','')
 # Retain failure injection and the production parser, use a distinct packed main.
 source=prefix+r'''
int main(int argc,char **argv){
 assert(argc==3);FILE *fp=fopen(argv[1],"rb");assert(fp);fseek(fp,0,SEEK_END);image_size=ftell(fp);rewind(fp);
 image=malloc(image_size);assert(image&&fread(image,1,image_size,fp)==image_size);fclose(fp);
 reset();EFI_FILE_PROTOCOL *f;UINTN n;KERNEL k;
 assert(open_kernel(&k,&f,&n)==0 && f!=&file && n>image_size);
 UINTN open_allocs=allocations,open_reads=reads;
 UINT8 *window=calloc(1,WINDOW_SIZE);assert(window);
 assert(StreamKernel(f,n,&k,(UINTN)window,WINDOW_SIZE)==0);
 fp=fopen(argv[2],"wb");assert(fp&&fwrite(window,1,k.End-k.Base,fp)==k.End-k.Base);fclose(fp);
 assert(f->Close(f)==0&&closes==1&&!live);free(window);
 // Reader handles arbitrary offsets, short reads, EOF and one cached block.
 reset();partial=997;f=&file;n=image_size;assert(MkOpen(&f,&n)==0);
 UINT8 b[70000];UINTN got=sizeof b;assert(f->SetPosition(f,65530)==0 && f->Read(f,&got,b)==0 && got==sizeof b);
 assert(f->SetPosition(f,MAX_UINT64)==0);got=1;assert(f->Read(f,&got,b)==0&&!got);
 assert(f->SetPosition(f,n+1)==EFI_BAD_BUFFER_SIZE);assert(f->Close(f)==0&&!live);
 for(UINTN i=1;i<=open_allocs;i++){reset();failalloc=i;refused();}
 for(UINTN i=1;i<=open_reads;i++){reset();failread=(int)i;refused();}
 // Corrupt metadata including re-CRC'd invalid ranges: no leaks, no raw fallback.
 const UINTN positions[]={8,12,16,24,32,36,72,76,96,104,108,116};
 for(UINTN i=0;i<sizeof positions/sizeof positions[0];i++){
  UINTN off=positions[i];UINT8 save=image[off];UINT32 oldcrc=U32(image+72);image[off]^=0x80;
  if(off>=96)put32(image+72,MkCrc(image+96,U32(image+32)*24));
  reset();refused();image[off]=save;put32(image+72,oldcrc);
 }
 reset();f=&file;n=image_size;assert(MkOpen(&f,&n)==0);
 UINT64 first=U64(image+96);image[first]^=0x40;got=1;assert(f->Read(f,&got,b)!=0);image[first]^=0x40;
 assert(f->Close(f)==0&&!live);
 // All fixed-header truncations and tail truncation are rejected.
 UINTN full=image_size;for(UINTN i=8;i<96;i++){image_size=i;reset();refused();}
 image_size=full-1;reset();refused();image_size=full;
 free(image);printf("PASS: packed EFI streaming, metadata corruption, short I/O, allocation/read failures, EOF and bounded pools\n");return 0;
}
'''
 (t/'host.c').write_text(source)
 header=(a.device/'loader/KernelStream.h').read_text()
 if 'MkOpen' not in header:
  needle='  *FileSize = (UINTN)Info->FileSize;'
  assert header.count(needle)==1
  header=header.replace(needle,needle+'\n  Status = MkOpen (&File, FileSize);\n  if (EFI_ERROR (Status)) { goto Done; }')
 (t/'KernelStream.h').write_text(header)
 cmd=[a.cc,'-std=c11','-g','-O1','-fno-pie','-no-pie','-fno-omit-frame-pointer','-fsanitize=address,undefined','-Wall','-Wextra','-Werror','-Wno-unused-function','-I'+str(t),'-I'+str(here),str(t/'host.c'),'-o',str(t/'host')]
 subprocess.run(cmd,check=True)
 env=dict(os.environ,ASAN_OPTIONS='detect_leaks=0:halt_on_error=1',UBSAN_OPTIONS='halt_on_error=1')
 subprocess.run([str(t/'host'),str(t/'kernel.packed'),str(t/'mapped')],check=True,env=env)
 segments=[];at=32
 for _ in range(struct.unpack_from('<I',raw,16)[0]):
  command,size=struct.unpack_from('<II',raw,at)
  if command==0x19:
   va,sz,fo,fs=struct.unpack_from('<4Q',raw,at+24)
   if sz:segments.append((va,sz,fo,fs))
  at+=size
 low=min(s[0] for s in segments);end=max(s[0]+s[1] for s in segments);expected=bytearray(end-low)
 for va,sz,fo,fs in segments:expected[va-low:va-low+fs]=raw[fo:fo+fs]
 assert (t/'mapped').read_bytes()==expected
 # Differential decoder uses actual production code; each case runs under sanitizers.
 decoder=prefix[:prefix.index('#include "MyronPackedKernel.h"')]+r'''
#include "MyronPackedKernel.h"
int main(int argc,char **argv){assert(argc==2);FILE *fp=fopen(argv[1],"rb");assert(fp);UINT32 n,size;UINT8 in[65536],out[65536],want[65536];unsigned count=0;
 while(fread(&n,4,1,fp)==1){assert(fread(&size,4,1,fp)==1 && n<=65536 && size<=65536);assert(fread(in,1,n,fp)==n&&fread(want,1,size,fp)==size);assert(MkLz4(in,n,out,size)&&!memcmp(out,want,size));count++;}
 fclose(fp);
 const UINT8 bad[][8]={{0x10,'a',0,0},{0x10,'a',2,0},{0xf0,255,255},{0,1,0},{0x1f,'a',1,0,255,255}};
 const unsigned lens[]={4,4,3,3,6};
 for(unsigned i=0;i<5;i++)assert(!MkLz4(bad[i],lens[i],out,32));
 printf("PASS: %u reference LZ4 blocks and malformed offset/length cases\n",count);return 0;}
'''
 (t/'decoder.c').write_text(decoder.replace('static int gEfiFileInfoGuid;', ''));cmd[-3:]=[str(t/'decoder.c'),'-o',str(t/'decoder')];subprocess.run(cmd,check=True)
 import lz4.block
 rng=random.Random(0x8850)
 with (t/'vectors').open('wb') as out:
  for i in range(600):
   size=rng.choice([0,1,4,12,15,255,256,65535,65536,rng.randrange(65537)])
   value=(rng.randbytes(size) if i%3==0 else (rng.randbytes(rng.randrange(1,128))*65536)[:size])
   compressed=lz4.block.compress(value,store_size=False)
   if len(compressed)>65536:continue
   out.write(struct.pack('<II',len(compressed),len(value))+compressed+value)
 subprocess.run([str(t/'decoder'),str(t/'vectors')],check=True,env=env)
 print(f'PASS: all Mach-O segments independently equal; original={len(raw)} transport={len(packed)} original_sha256={a.sha256}')
